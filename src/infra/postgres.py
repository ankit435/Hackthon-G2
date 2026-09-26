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

_CHUNK_COLUMNS = ("id, audio_file_id, chunk_index, speaker_id, text, start_time, end_time, embedding, "
                  "prev_chunk_id, next_chunk_id, token_count, char_count")


class PostgresRepository:
    """Implements AudioFileRepository and ChunkRepository. Search methods arrive in Task 5."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    async def _connect(self) -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(self._url)
        await register_vector_async(conn)
        return conn

    async def find_by_checksum(self, checksum: str) -> AudioFile | None:
        try:
            async with await self._connect() as conn:
                row = await (await conn.execute(
                    "SELECT id, file_name, file_path, checksum, duration_seconds, created_at FROM audio_file WHERE checksum = %s",
                    (checksum,))).fetchone()
        except psycopg.Error as e:
            raise RepositoryError("lookup by checksum failed", stage="persist", error=type(e).__name__) from e
        return AudioFile(id=row[0], file_name=row[1], file_path=row[2], checksum=row[3],
                         duration_seconds=row[4], created_at=row[5]) if row else None

    async def add_with_chunks(self, audio_file: AudioFile, chunks: Sequence[Chunk]) -> None:
        try:
            async with await self._connect() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO audio_file (id, file_name, file_path, checksum, duration_seconds) VALUES (%s,%s,%s,%s,%s)",
                    (audio_file.id, audio_file.file_name, audio_file.file_path, audio_file.checksum,
                     audio_file.duration_seconds))
                async with conn.cursor() as cur:
                    await cur.executemany(
                        f"INSERT INTO chunk ({_CHUNK_COLUMNS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(c.id, c.audio_file_id, c.chunk_index, c.speaker, c.text, c.start_time, c.end_time,
                          None if c.embedding is None else np.asarray(c.embedding, dtype=np.float32),
                          c.prev_chunk_id, c.next_chunk_id, c.token_count, c.char_count) for c in chunks])
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
                      prev_chunk_id=r[8], next_chunk_id=r[9], token_count=r[10], char_count=r[11]) for r in rows]

    async def keyword_search(self, query: str, limit: int) -> list[BranchHit]:
        raise NotImplementedError("Task 5")

    async def semantic_search(self, query_embedding: Sequence[float], limit: int) -> list[BranchHit]:
        raise NotImplementedError("Task 5")

    async def hydrate(self, chunk_ids: Sequence[UUID]) -> list[SearchResultItem]:
        raise NotImplementedError("Task 5")
