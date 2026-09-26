"""Search methods of PostgresRepository against the live DB.

Robust to the real golden chunks sharing the database: keyword tests use nonsense tokens that
cannot occur in the corpus, and semantic tests use a vector orthogonal-by-construction plus an exact
match, so the test rows rank deterministically. Each test deletes its own rows (by checksum).
"""
import asyncio
import uuid

import psycopg
import pytest

from api.settings import load_settings
from domain.models import AudioFile, Chunk
from psycopg.conninfo import make_conninfo

from infra.postgres import SEMANTIC_SQL, PostgresRepository

URL = load_settings().database_url
# The golden table is small enough that the planner prefers a sequential scan, which would hide
# HNSW-specific behaviour (ef_search truncation, index usability). This connection forbids it.
INDEX_ONLY_URL = make_conninfo(URL, options="-c enable_seqscan=off")
DIM = 384


def one_hot(i: int) -> tuple[float, ...]:
    return tuple(1.0 if j == i else 0.0 for j in range(DIM))


def _linked_ids(n):
    ids = [uuid.uuid4() for _ in range(n)]
    return [(ids[i], ids[i - 1] if i else None, ids[i + 1] if i + 1 < n else None) for i in range(n)]


@pytest.fixture
def seeded():
    """Three chunks with nonsense vocabulary and near-one-hot embeddings in a fresh audio_file."""
    f = AudioFile(file_name="search-test.wav", file_path="/tmp/search-test.wav",
                  checksum=f"test-{uuid.uuid4().hex}", duration_seconds=30.0)
    texts = ["We zorbified the qwibble ledgers yesterday.",
             "Nobody zorbifies a qwibble twice; qwibble qwibble.",
             "Flarnish the blorptastic crumbulator."]
    # Tiny values elsewhere keep cosine well-defined and distinct; dimension 383 is a spike none of the real
    # MiniLM vectors align with exactly, so the exact-match row must rank first.
    vectors = [tuple(v + 1e-3 for v in one_hot(383 - i)) for i in range(3)]
    chunks = [Chunk(id=cid, audio_file_id=f.id, chunk_index=i, speaker=f"SPEAKER_0{i % 2}", text=texts[i],
                    start_time=10.0 * i, end_time=10.0 * i + 8.0, token_count=12, char_count=len(texts[i]),
                    prev_chunk_id=prev, next_chunk_id=nxt, embedding=vectors[i])
              for i, (cid, prev, nxt) in enumerate(_linked_ids(3))]
    asyncio.run(PostgresRepository(URL).add_with_chunks(f, chunks))
    yield f, chunks, vectors
    with psycopg.connect(URL) as c:
        c.execute("DELETE FROM audio_file WHERE checksum = %s", (f.checksum,))


def repo(ef=40):
    return PostgresRepository(URL, hnsw_ef_search=ef)


def test_keyword_stemming_through_the_real_query_path(seeded):
    _, chunks, _ = seeded
    got = asyncio.run(repo().keyword_search("zorbifying", 10))  # stems like zorbified / zorbifies
    assert {h.chunk_id for h in got} == {chunks[0].id, chunks[1].id}
    assert [h.rank for h in got] == [1, 2]


def test_keyword_ranks_best_first_with_saturated_scores(seeded):
    _, chunks, _ = seeded
    got = asyncio.run(repo().keyword_search("qwibble", 10))
    assert got[0].chunk_id == chunks[1].id  # three occurrences beat one
    assert all(0 < h.score < 1 for h in got) and got[0].score >= got[1].score


def test_keyword_phrase_and_exclusion_syntax(seeded):
    _, chunks, _ = seeded
    assert [h.chunk_id for h in asyncio.run(repo().keyword_search('"qwibble ledgers"', 10))] == [chunks[0].id]
    assert [h.chunk_id for h in asyncio.run(repo().keyword_search("qwibble -ledgers", 10))] == [chunks[1].id]


def test_keyword_stop_word_only_query_returns_empty():
    assert asyncio.run(repo().keyword_search("the and of", 10)) == []


@pytest.mark.parametrize("query", ['"unclosed', "OR OR -", "((", "!!!"])
def test_keyword_malformed_input_does_not_raise(query):
    asyncio.run(repo().keyword_search(query, 10))


def test_keyword_respects_limit(seeded):
    assert len(asyncio.run(repo().keyword_search("qwibble", 1))) == 1


def test_semantic_exact_vector_ranks_first_with_similarity_one(seeded):
    _, chunks, vectors = seeded
    got = asyncio.run(repo().semantic_search(vectors[2], 5))
    assert got[0].chunk_id == chunks[2].id and got[0].rank == 1
    assert got[0].score == pytest.approx(1.0, abs=1e-5)
    assert [h.rank for h in got] == list(range(1, len(got) + 1))
    assert all(a.score >= b.score for a, b in zip(got, got[1:]))


def test_semantic_depth_is_not_truncated_by_hnsw(seeded):
    # On the HNSW path a plain scan returns at most ef_search rows and often fewer than LIMIT
    # (measured 2 of 20 at ef_search=5). Iterative scanning must deliver the full depth.
    got = asyncio.run(PostgresRepository(INDEX_ONLY_URL, hnsw_ef_search=5).semantic_search(seeded[2][0], 20))
    with psycopg.connect(URL) as c:
        available = c.execute("SELECT count(*) FROM chunk WHERE embedding IS NOT NULL").fetchone()[0]
    assert len(got) == min(20, available)
    # strict_order: row position must be a true rank (relaxed_order may return rows slightly out of order)
    assert all(a.score >= b.score for a, b in zip(got, got[1:]))


def test_semantic_skips_chunks_without_embeddings(seeded):
    f, _, _ = seeded
    with psycopg.connect(URL) as c:
        c.execute("UPDATE chunk SET embedding = NULL WHERE audio_file_id = %s AND chunk_index = 2", (f.id,))
    got = asyncio.run(repo().semantic_search(seeded[2][2], 400))
    assert seeded[1][2].id not in {h.chunk_id for h in got}


def test_hydrate_joins_file_and_dedupes(seeded):
    f, chunks, _ = seeded
    items = asyncio.run(repo().hydrate([chunks[1].id, chunks[0].id, chunks[1].id, uuid.uuid4()]))
    assert sorted(i.chunk_id for i in items) == sorted([chunks[0].id, chunks[1].id])  # unknown id simply absent
    item = next(i for i in items if i.chunk_id == chunks[1].id)
    assert (item.file_name, item.file_path, item.audio_file_id) == (f.file_name, f.file_path, f.id)
    assert (item.speaker, item.start_time, item.end_time, item.text) == ("SPEAKER_01", 10.0, 18.0, chunks[1].text)


def test_hydrate_empty():
    assert asyncio.run(repo().hydrate([])) == []


def test_semantic_sql_is_served_by_the_hnsw_index():
    """The repository's own SQL, not a hand-written copy: ordering by an alias would disable the index."""
    vec = "[" + ",".join(["0.1"] * DIM) + "]"
    with psycopg.connect(URL) as c:
        c.execute("SET enable_seqscan = off")
        plan = "\n".join(r[0] for r in c.execute("EXPLAIN " + SEMANTIC_SQL.replace("%s", "%s::vector", 2), (vec, vec, 10)))
    assert "chunk_embedding_hnsw" in plan
