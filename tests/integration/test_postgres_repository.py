"""PostgresRepository against the live database. Every test deletes what it wrote (by checksum, cascading)."""
import asyncio
import uuid

import psycopg
import pytest

from api.settings import load_settings
from application.chunking import link
from domain.errors import RepositoryError
from domain.models import AudioFile, Chunk
from infra.postgres import PostgresRepository

URL = load_settings().database_url


@pytest.fixture
def audio_file():
    f = AudioFile(file_name="t.wav", file_path="/tmp/t.wav", checksum=f"test-{uuid.uuid4().hex}", duration_seconds=12.5,
                  language="es", language_probability=0.97)
    yield f
    with psycopg.connect(URL) as c:
        c.execute("DELETE FROM audio_file WHERE checksum = %s", (f.checksum,))


def make_chunks(audio_file, n, embedding=(0.1,) * 384):
    return [Chunk(id=cid, audio_file_id=audio_file.id, chunk_index=i, speaker=f"SPEAKER_0{i % 2}", text=f"chunk {i}",
                  start_time=i * 2.0, end_time=i * 2.0 + 1.5, token_count=4, char_count=7, language=audio_file.language,
                  prev_chunk_id=prev, next_chunk_id=nxt, embedding=embedding)
            for i, (cid, prev, nxt) in enumerate(link(n))]


def test_round_trip_preserves_every_field(audio_file):
    repo = PostgresRepository(URL)
    chunks = make_chunks(audio_file, 3)
    asyncio.run(repo.add_with_chunks(audio_file, chunks))
    found = asyncio.run(repo.find_by_checksum(audio_file.checksum))
    assert (found.id, found.file_name, found.duration_seconds) == (audio_file.id, "t.wav", 12.5)
    assert (found.language, found.language_probability) == ("es", 0.97)
    back = asyncio.run(repo.list_by_file(audio_file.id))
    assert [(c.id, c.chunk_index, c.speaker, c.text, c.start_time, c.end_time, c.prev_chunk_id, c.next_chunk_id)
            for c in back] == [(c.id, c.chunk_index, c.speaker, c.text, c.start_time, c.end_time,
                                c.prev_chunk_id, c.next_chunk_id) for c in chunks]
    assert len(back[0].embedding) == 384 and back[0].embedding[0] == pytest.approx(0.1)
    assert {c.language for c in back} == {"es"}


def test_missing_checksum_returns_none():
    assert asyncio.run(PostgresRepository(URL).find_by_checksum("no-such-checksum")) is None


def test_failure_mid_write_leaves_nothing(audio_file):
    repo = PostgresRepository(URL)
    chunks = make_chunks(audio_file, 3)
    bad = chunks[:2] + [make_chunks(audio_file, 3, embedding=(0.1,) * 383)[2]]  # last chunk: wrong dimension
    with pytest.raises(RepositoryError, match="nothing was written"):
        asyncio.run(repo.add_with_chunks(audio_file, bad))
    assert asyncio.run(repo.find_by_checksum(audio_file.checksum)) is None


def test_duplicate_checksum_is_a_repository_error(audio_file):
    repo = PostgresRepository(URL)
    asyncio.run(repo.add_with_chunks(audio_file, make_chunks(audio_file, 1)))
    twin = AudioFile(file_name="t2.wav", file_path="/tmp/t2.wav", checksum=audio_file.checksum, duration_seconds=1.0,
                     language="en", language_probability=1.0)
    with pytest.raises(RepositoryError):
        asyncio.run(repo.add_with_chunks(twin, make_chunks(twin, 1)))
