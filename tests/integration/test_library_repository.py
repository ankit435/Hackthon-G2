"""Library queries of PostgresRepository against the live DB (list_files, get_file, get_chunk).

Each test creates its own file(s) under a unique checksum and deletes them afterwards, so the real
golden rows sharing the database are never touched and never affect the assertions.
"""
import asyncio
import uuid

import psycopg
import pytest

from api.settings import load_settings
from domain.models import AudioFile, Chunk
from infra.postgres import PostgresRepository

URL = load_settings().database_url


def _file(name):
    return AudioFile(file_name=name, file_path=f"/tmp/{name}", checksum=f"test-lib-{uuid.uuid4().hex}",
                     duration_seconds=20.0, language="hi", language_probability=0.9)


def _chunks(f, speakers):
    ids = [uuid.uuid4() for _ in speakers]
    return [Chunk(id=ids[i], audio_file_id=f.id, chunk_index=i, speaker=s, text=f"नमस्ते {i}", start_time=5.0 * i,
                  end_time=5.0 * i + 4, token_count=4, char_count=8, language="hi",
                  prev_chunk_id=ids[i - 1] if i else None, next_chunk_id=ids[i + 1] if i + 1 < len(ids) else None)
            for i, s in enumerate(speakers)]


@pytest.fixture
def seeded():
    repo = PostgresRepository(URL)
    f = _file(f"zz-lib-{uuid.uuid4().hex[:6]}.wav")
    chunks = _chunks(f, ["SPEAKER_01", "SPEAKER_00", "SPEAKER_01"])
    asyncio.run(repo.add_with_chunks(f, chunks))
    yield repo, f, chunks
    with psycopg.connect(URL) as c:
        c.execute("DELETE FROM audio_file WHERE checksum = %s", (f.checksum,))


def test_list_files_reports_chunk_count_and_distinct_speakers(seeded):
    repo, f, _ = seeded
    [row] = [r for r in asyncio.run(repo.list_files()) if r.file.id == f.id]
    assert row.chunk_count == 3 and row.speakers == ("SPEAKER_00", "SPEAKER_01")
    assert (row.file.file_name, row.file.language, row.file.created_at is not None) == (f.file_name, "hi", True)


def test_list_files_includes_a_file_with_no_chunks():
    repo, f = PostgresRepository(URL), _file(f"zz-empty-{uuid.uuid4().hex[:6]}.wav")
    asyncio.run(repo.add_with_chunks(f, []))
    try:
        [row] = [r for r in asyncio.run(repo.list_files()) if r.file.id == f.id]
        assert (row.chunk_count, row.speakers) == (0, ())
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM audio_file WHERE checksum = %s", (f.checksum,))


def test_get_file_and_get_chunk(seeded):
    repo, f, chunks = seeded
    assert asyncio.run(repo.get_file(f.id)).checksum == f.checksum
    got = asyncio.run(repo.get_chunk(chunks[1].id))
    assert (got.chunk_index, got.speaker, got.text) == (1, "SPEAKER_00", "नमस्ते 1")
    assert (got.prev_chunk_id, got.next_chunk_id) == (chunks[0].id, chunks[2].id)
    assert asyncio.run(repo.get_file(uuid.uuid4())) is None and asyncio.run(repo.get_chunk(uuid.uuid4())) is None
