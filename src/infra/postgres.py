"""Postgres adapters. All SQL in the project lives here."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import numpy as np
import psycopg
from pgvector.psycopg import register_vector_async

from domain.errors import RepositoryError
from domain.models import AudioFile, BranchHit, Chunk, LibraryFile, SearchResultItem
from infra.text_search import cjk_bigrams, config_for

# ts_rank_cd normalization: 1 divides by 1 + log(document length), so a longer chunk cannot win
# just by repeating a term but is not punished harshly; 32 maps rank to rank/(rank+1), bounding
# scores to [0, 1). Together they approximate BM25-style saturation + length normalization.
TS_RANK_NORMALIZATION = 1 | 32

# websearch_to_tsquery never raises on malformed input and honours "quotes", OR, -exclusions.
# A stop-word-only query yields an empty tsquery that matches nothing, so the result is [].
# Ties on score break by id, so row position (the rank fusion consumes) is deterministic.
#
# Each chunk carries its own `search_config` (PLAN.md §7B, M5; infra.text_search): a query is run
# ONCE PER DISTINCT CONFIG PRESENT, scoped to that config's rows, then merged. This keeps
# websearch_to_tsquery(cfg, ...) a per-pass constant so the planner can use the GIN index within
# each pass — a single query with a per-row config (`websearch_to_tsquery(search_config, ...)`)
# would force a sequential scan, since the tsquery operand would vary row to row.
# ORDER BY the raw <=> operator (not the alias) so the planner can use the HNSW index.
SEMANTIC_SQL = ("SELECT id, 1 - (embedding <=> %s) AS similarity FROM chunk "
                "WHERE embedding IS NOT NULL ORDER BY embedding <=> %s LIMIT %s")
HYDRATE_SQL = ("SELECT c.id, c.audio_file_id, a.file_name, a.file_path, c.speaker_id, c.start_time, c.end_time, c.text, "
               "c.language "
               "FROM chunk c JOIN audio_file a ON a.id = c.audio_file_id WHERE c.id = ANY(%s)")

_CHUNK_COLUMNS = ("id, audio_file_id, chunk_index, speaker_id, text, start_time, end_time, embedding, "
                  "prev_chunk_id, next_chunk_id, token_count, char_count, language")
# search_config/search_text are derived, write-only (from `language`/`text`); not read back onto the
# domain Chunk model, so they are appended here rather than folded into _CHUNK_COLUMNS above.
_CHUNK_INSERT_COLUMNS = _CHUNK_COLUMNS + ", search_config, search_text"


def _audio_file(r) -> AudioFile:
    return AudioFile(id=r[0], file_name=r[1], file_path=r[2], checksum=r[3], duration_seconds=r[4], created_at=r[5],
                     language=r[6], language_probability=r[7])


def _chunk(r) -> Chunk:
    return Chunk(id=r[0], audio_file_id=r[1], chunk_index=r[2], speaker=r[3], text=r[4], start_time=r[5],
                 end_time=r[6], embedding=None if r[7] is None else tuple(r[7].to_list()),
                 prev_chunk_id=r[8], next_chunk_id=r[9], token_count=r[10], char_count=r[11], language=r[12])


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
                # The configs Postgres actually has (a fresh install may be missing an optional
                # dictionary); config_for falls back to 'simple' + WARNING for anything not present.
                available = {r[0] for r in await (await conn.execute("SELECT cfgname FROM pg_ts_config")).fetchall()}
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO chunk ({_CHUNK_INSERT_COLUMNS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(c.id, c.audio_file_id, c.chunk_index, c.speaker, c.text, c.start_time, c.end_time,
                          None if c.embedding is None else np.asarray(c.embedding, dtype=np.float32),
                          c.prev_chunk_id, c.next_chunk_id, c.token_count, c.char_count, c.language,
                          config_for(c.language, available), cjk_bigrams(c.text)) for c in chunks])
        except psycopg.Error as e:
            raise RepositoryError("persisting file and chunks failed; nothing was written", stage="persist",
                                  file=audio_file.file_name, error=type(e).__name__, detail=str(e).splitlines()[0]) from e

    async def list_files(self) -> list[LibraryFile]:
        try:
            async with await self._connect() as conn:
                rows = await (await conn.execute(
                    "SELECT f.id, f.file_name, f.file_path, f.checksum, f.duration_seconds, f.created_at, f.language, "
                    "f.language_probability, count(c.id), "
                    "coalesce(array_agg(DISTINCT c.speaker_id) FILTER (WHERE c.id IS NOT NULL), '{}') "
                    "FROM audio_file f LEFT JOIN chunk c ON c.audio_file_id = f.id "
                    "GROUP BY f.id ORDER BY f.file_name, f.id")).fetchall()
        except psycopg.Error as e:
            raise RepositoryError("listing files failed", stage="library", error=type(e).__name__) from e
        return [LibraryFile(file=_audio_file(r), chunk_count=r[8], speakers=tuple(sorted(r[9]))) for r in rows]

    async def get_file(self, audio_file_id: UUID) -> AudioFile | None:
        try:
            async with await self._connect() as conn:
                row = await (await conn.execute(
                    "SELECT id, file_name, file_path, checksum, duration_seconds, created_at, language, "
                    "language_probability FROM audio_file WHERE id = %s", (audio_file_id,))).fetchone()
        except psycopg.Error as e:
            raise RepositoryError("file lookup failed", stage="library", error=type(e).__name__) from e
        return _audio_file(row) if row else None

    async def get_chunk(self, chunk_id: UUID) -> Chunk | None:
        try:
            async with await self._connect() as conn:
                row = await (await conn.execute(
                    f"SELECT {_CHUNK_COLUMNS} FROM chunk WHERE id = %s", (chunk_id,))).fetchone()
        except psycopg.Error as e:
            raise RepositoryError("chunk lookup failed", stage="library", error=type(e).__name__) from e
        return _chunk(row) if row else None

    async def list_by_file(self, audio_file_id: UUID) -> list[Chunk]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(
                f"SELECT {_CHUNK_COLUMNS} FROM chunk WHERE audio_file_id = %s ORDER BY chunk_index",
                (audio_file_id,))).fetchall()
        return [_chunk(r) for r in rows]

    async def keyword_search(self, query: str, limit: int) -> list[BranchHit]:
        bigrammed = cjk_bigrams(query)  # identity unless the query itself contains CJK text
        try:
            async with await self._connect() as conn:
                configs = [r[0] for r in await (await conn.execute(
                    "SELECT DISTINCT search_config::text FROM chunk")).fetchall()]
                if not configs:
                    return []
                # One pass per config present, UNION ALL'd: within each pass the tsquery is a
                # constant (see the module comment above), then merged and re-ranked across passes.
                passes = " UNION ALL ".join(
                    "(SELECT id, ts_rank_cd(text_search, websearch_to_tsquery(%s::regconfig, %s), %s) AS score "
                    "FROM chunk WHERE search_config = %s::regconfig "
                    "AND text_search @@ websearch_to_tsquery(%s::regconfig, %s))" for _ in configs)
                sql = f"SELECT id, score FROM ({passes}) AS per_config ORDER BY score DESC, id LIMIT %s"
                params = [v for cfg in configs for v in (cfg, bigrammed, TS_RANK_NORMALIZATION, cfg, cfg, bigrammed)]
                rows = await (await conn.execute(sql, params + [limit])).fetchall()
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
