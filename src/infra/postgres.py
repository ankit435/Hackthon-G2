"""Postgres adapters. All SQL in the project lives here."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import numpy as np
import psycopg
from pgvector.psycopg import register_vector_async

from domain.errors import RepositoryError
from domain.models import AudioFile, BranchHit, Chunk, SearchResultItem

# Must equal the configuration of chunk.text_search in db/schema.sql. Queries parse with this
# (websearch_to_tsquery(TEXT_SEARCH_CONFIG, ...)); a mismatch silently loses matches.
# tests/integration/test_schema.py asserts both sides agree.
TEXT_SEARCH_CONFIG = "english"

# ts_rank_cd normalization: 1 divides by 1 + log(document length), so a longer chunk cannot win
# just by repeating a term but is not punished harshly; 32 maps rank to rank/(rank+1), bounding
# scores to [0, 1). Together they approximate BM25-style saturation + length normalization.
TS_RANK_NORMALIZATION = 1 | 32

# websearch_to_tsquery never raises on malformed input and honours "quotes", OR, -exclusions.
# A stop-word-only query yields an empty tsquery that matches nothing, so the result is [].
# Ties on score break by id, so row position (the rank fusion consumes) is deterministic.
KEYWORD_SQL = ("SELECT id, ts_rank_cd(text_search, q, %s) AS score "
               "FROM chunk, websearch_to_tsquery(%s::regconfig, %s) AS q "
               "WHERE text_search @@ q ORDER BY score DESC, id LIMIT %s")
# ORDER BY the raw <=> operator (not the alias) so the planner can use the HNSW index.
SEMANTIC_SQL = ("SELECT id, 1 - (embedding <=> %s) AS similarity FROM chunk "
                "WHERE embedding IS NOT NULL ORDER BY embedding <=> %s LIMIT %s")
HYDRATE_SQL = ("SELECT c.id, c.audio_file_id, a.file_name, a.file_path, c.speaker_id, c.start_time, c.end_time, c.text, "
               "c.language "
               "FROM chunk c JOIN audio_file a ON a.id = c.audio_file_id WHERE c.id = ANY(%s)")

_CHUNK_COLUMNS = ("id, audio_file_id, chunk_index, speaker_id, text, start_time, end_time, embedding, "
                  "prev_chunk_id, next_chunk_id, token_count, char_count, language")


class PostgresRepository:
    """Implements AudioFileRepository and ChunkRepository."""

    def __init__(self, database_url: str, hnsw_ef_search: int | None = None) -> None:
        self._url = database_url
        self._ef_search = hnsw_ef_search  # None: leave the server default (ingest-only use)

    async def _connect(self) -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(self._url)
        await register_vector_async(conn)
        return conn

    async def find_by_checksum(self, checksum: str) -> AudioFile | None:
        try:
            async with await self._connect() as conn:
                row = await (await conn.execute(
                    "SELECT id, file_name, file_path, checksum, duration_seconds, created_at, language, language_probability "
                    "FROM audio_file WHERE checksum = %s",
                    (checksum,))).fetchone()
        except psycopg.Error as e:
            raise RepositoryError("lookup by checksum failed", stage="persist", error=type(e).__name__) from e
        return AudioFile(id=row[0], file_name=row[1], file_path=row[2], checksum=row[3],
                         duration_seconds=row[4], created_at=row[5], language=row[6],
                         language_probability=row[7]) if row else None

    async def add_with_chunks(self, audio_file: AudioFile, chunks: Sequence[Chunk]) -> None:
        try:
            async with await self._connect() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO audio_file (id, file_name, file_path, checksum, duration_seconds, language, "
                    "language_probability) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (audio_file.id, audio_file.file_name, audio_file.file_path, audio_file.checksum,
                     audio_file.duration_seconds, audio_file.language, audio_file.language_probability))
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO chunk ({_CHUNK_COLUMNS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(c.id, c.audio_file_id, c.chunk_index, c.speaker, c.text, c.start_time, c.end_time,
                          None if c.embedding is None else np.asarray(c.embedding, dtype=np.float32),
                          c.prev_chunk_id, c.next_chunk_id, c.token_count, c.char_count, c.language) for c in chunks])
        except psycopg.Error as e:
            raise RepositoryError("persisting file and chunks failed; nothing was written", stage="persist",
                                  file=audio_file.file_name, error=type(e).__name__, detail=str(e).splitlines()[0]) from e

    async def list_by_file(self, audio_file_id: UUID) -> list[Chunk]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(
                f"SELECT {_CHUNK_COLUMNS} FROM chunk WHERE audio_file_id = %s ORDER BY chunk_index",
                (audio_file_id,))).fetchall()
        return [Chunk(id=r[0], audio_file_id=r[1], chunk_index=r[2], speaker=r[3], text=r[4], start_time=r[5],
                      end_time=r[6], embedding=None if r[7] is None else tuple(r[7].to_list()),
                      prev_chunk_id=r[8], next_chunk_id=r[9], token_count=r[10], char_count=r[11], language=r[12])
                for r in rows]

    async def keyword_search(self, query: str, limit: int) -> list[BranchHit]:
        try:
            async with await self._connect() as conn:
                rows = await (await conn.execute(KEYWORD_SQL, (TS_RANK_NORMALIZATION, TEXT_SEARCH_CONFIG, query, limit))).fetchall()
        except psycopg.Error as e:
            raise RepositoryError("keyword search failed", stage="search.keyword", error=type(e).__name__) from e
        return [BranchHit(chunk_id=r[0], rank=i, score=float(r[1])) for i, r in enumerate(rows, start=1)]

    async def semantic_search(self, query_embedding: Sequence[float], limit: int) -> list[BranchHit]:
        vector = np.asarray(query_embedding, dtype=np.float32)
        try:
            async with await self._connect() as conn, conn.transaction():
                # A plain HNSW scan can return FEWER than LIMIT rows (measured: 37 of 50 at ef_search=40),
                # silently shrinking the branch. Iterative scanning (pgvector >= 0.8) keeps going until LIMIT
                # is met; strict_order preserves exact distance order, so row position is a true rank.
                await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
                if self._ef_search is not None:
                    await conn.execute(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}")
                rows = await (await conn.execute(SEMANTIC_SQL, (vector, vector, limit))).fetchall()
        except psycopg.Error as e:
            raise RepositoryError("semantic search failed", stage="search.semantic", error=type(e).__name__) from e
        return [BranchHit(chunk_id=r[0], rank=i, score=float(r[1])) for i, r in enumerate(rows, start=1)]

    async def hydrate(self, chunk_ids: Sequence[UUID]) -> list[SearchResultItem]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return []
        try:
            async with await self._connect() as conn:
                rows = await (await conn.execute(HYDRATE_SQL, (ids,))).fetchall()
        except psycopg.Error as e:
            raise RepositoryError("hydrating results failed", stage="search.hydrate", error=type(e).__name__) from e
        return [SearchResultItem(chunk_id=r[0], audio_file_id=r[1], file_name=r[2], file_path=r[3], speaker=r[4],
                                 start_time=r[5], end_time=r[6], text=r[7], language=r[8], score=0.0) for r in rows]
