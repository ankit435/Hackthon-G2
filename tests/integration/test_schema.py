"""Live-database checks of db/schema.sql (PLAN.md §4A step 6, Rule 13).

Requires Postgres at AUDIO_SEARCH_DATABASE_URL with the schema applied (python scripts/init_db.py).
An unreachable database fails these tests; it is never a skip.
Every write happens inside a transaction that is rolled back.
"""
import uuid

import psycopg
import pytest

from api.settings import load_settings
from infra.text_search import cjk_bigrams


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(load_settings().database_url) as c:
        yield c


@pytest.fixture
def tx(conn):
    with conn.transaction(force_rollback=True):
        yield conn


def insert_file(c) -> uuid.UUID:
    fid = uuid.uuid4()
    c.execute("INSERT INTO audio_file (id, file_name, file_path, checksum, duration_seconds, language, language_probability) "
              "VALUES (%s,'t.wav','/t.wav',%s,10,'en',1.0)",
              (fid, uuid.uuid4().hex))
    return fid


def insert_chunk(c, fid, idx, text, embedding=None, prev=None, next_=None, cid=None,
                 language="en", search_config="english", search_text=None) -> uuid.UUID:
    cid = cid or uuid.uuid4()
    search_text = search_text if search_text is not None else cjk_bigrams(text)
    c.execute("""INSERT INTO chunk (id, audio_file_id, chunk_index, speaker_id, text, start_time, end_time,
                                    embedding, prev_chunk_id, next_chunk_id, token_count, char_count, language,
                                    search_config, search_text)
                 VALUES (%s,%s,%s,'SPEAKER_00',%s,%s,%s,%s::vector,%s,%s,5,%s,%s,%s::regconfig,%s)""",
              (cid, fid, idx, text, idx, idx + 1, embedding, prev, next_, len(text), language,
               search_config, search_text))
    return cid


def test_pgvector_extension_enabled(conn):
    assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()


def test_embedding_column_is_vector_1024(conn):
    typ = conn.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                       "WHERE attrelid='chunk'::regclass AND attname='embedding'").fetchone()[0]
    assert typ == "vector(1024)"


def test_generated_tsvector_uses_the_query_side_config(conn):
    """Per row now (M5): the generated column reads search_config/search_text, not a fixed literal."""
    expr = conn.execute("SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d JOIN pg_attribute a "
                        "ON a.attrelid=d.adrelid AND a.attnum=d.adnum "
                        "WHERE d.adrelid='chunk'::regclass AND a.attname='text_search'").fetchone()[0]
    assert expr == "to_tsvector(search_config, search_text)"


def test_indexes_exist_with_recorded_parameters(conn):
    defs = dict(conn.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='chunk'").fetchall())
    assert "USING gin (text_search)" in defs["chunk_text_search_gin"]
    hnsw = defs["chunk_embedding_hnsw"]
    assert "USING hnsw (embedding vector_cosine_ops)" in hnsw and "m='16'" in hnsw and "ef_construction='64'" in hnsw


def test_stemming_matches_inflections_through_the_generated_column(tx):
    fid = insert_file(tx)
    cid = insert_chunk(tx, fid, 0, "We archived the logs before rotating them.", search_config="english")
    for query in ("archiving", "archives", "rotate log"):
        # scoped to this test's file: the shared DB also holds real ingested chunks
        hit = tx.execute("SELECT id, ts_rank_cd(text_search, q, 32) FROM chunk, websearch_to_tsquery('english', %s) q "
                         "WHERE text_search @@ q AND audio_file_id = %s", (query, fid)).fetchall()
        assert [h[0] for h in hit] == [cid], query
        assert 0 < hit[0][1] < 1  # normalization flag 32 saturates the score into (0, 1)


def test_stemming_matches_inflections_in_spanish(tx):
    """M5: a non-English config stems too, as long as query and index sides agree on it."""
    fid = insert_file(tx)
    cid = insert_chunk(tx, fid, 0, "Archivamos los registros ayer.", language="es", search_config="spanish")
    hit = tx.execute("SELECT id, ts_rank_cd(text_search, q, 32) FROM chunk, websearch_to_tsquery('spanish', %s) q "
                     "WHERE text_search @@ q AND audio_file_id = %s", ("archivado", fid)).fetchall()
    assert [h[0] for h in hit] == [cid]


def test_cjk_bigrams_let_a_sub_phrase_match_inside_longer_chinese_text(tx):
    """M5: 'simple' has no CJK segmenter, so both index and query text are pre-bigrammed."""
    fid = insert_file(tx)
    text = "限流器很重要"
    cid = insert_chunk(tx, fid, 0, text, language="zh", search_config="simple", search_text=cjk_bigrams(text))
    hit = tx.execute("SELECT id FROM chunk, websearch_to_tsquery('simple', %s) q "
                     "WHERE text_search @@ q AND audio_file_id = %s", (cjk_bigrams("限流器"), fid)).fetchall()
    assert [h[0] for h in hit] == [cid]
    # a permutation sharing no bigram with the index text must NOT match
    assert not tx.execute("SELECT id FROM chunk, websearch_to_tsquery('simple', %s) q "
                          "WHERE text_search @@ q AND audio_file_id = %s", (cjk_bigrams("器很流"), fid)).fetchall()


def test_unmapped_language_falls_back_to_simple(tx, caplog):
    """M5: infra.text_search.config_for is what ingestion calls; verify its choice actually works end to end."""
    from infra.text_search import config_for

    available = {r[0] for r in tx.execute("SELECT cfgname FROM pg_ts_config").fetchall()}
    cfg = config_for("sw", available)  # Swahili: not in ISO_TO_CONFIG
    assert cfg == "simple"
    fid = insert_file(tx)
    cid = insert_chunk(tx, fid, 0, "Tulihifadhi kumbukumbu.", language="sw", search_config=cfg)
    hit = tx.execute("SELECT id FROM chunk, websearch_to_tsquery(%s, %s) q "
                     "WHERE text_search @@ q AND audio_file_id = %s", (cfg, "kumbukumbu", fid)).fetchall()
    assert [h[0] for h in hit] == [cid]


def test_config_mismatch_loses_the_match_silently(tx):
    """The trap per-row config exists to prevent: 'simple' does not stem, so nothing matches and nothing errors."""
    fid = insert_file(tx)
    insert_chunk(tx, fid, 0, "We archived the logs.", search_config="english")
    assert not tx.execute("SELECT 1 FROM chunk WHERE text_search @@ websearch_to_tsquery('simple', 'archiving') "
                          "AND audio_file_id = %s", (fid,)).fetchall()


def test_websearch_parser_degrades_gracefully_on_malformed_input(tx):
    for query in ('"unclosed phrase', "OR OR -", "((", ""):
        tx.execute("SELECT websearch_to_tsquery('english', %s)", (query,))


def test_wrong_embedding_dimension_is_rejected(tx):
    with pytest.raises(psycopg.errors.DataException, match="1024"):
        insert_chunk(tx, insert_file(tx), 0, "x", embedding=str([0.1] * 1023))


def test_hnsw_index_is_used_for_cosine_ordering(tx):
    fid = insert_file(tx)
    for i in range(3):
        insert_chunk(tx, fid, i, f"chunk {i}", embedding=str([float(i + 1)] + [0.0] * 1023))
    tx.execute("SET LOCAL enable_seqscan = off")  # tiny table: force the planner to show the index is usable
    plan = "\n".join(r[0] for r in tx.execute(
        "EXPLAIN SELECT id FROM chunk ORDER BY embedding <=> %s::vector LIMIT 2", (str([1.0] + [0.0] * 1023),)))
    assert "chunk_embedding_hnsw" in plan


def test_prev_next_links_are_checked_at_commit_not_insert(tx):
    fid = insert_file(tx)
    a, b = uuid.uuid4(), uuid.uuid4()
    insert_chunk(tx, fid, 0, "first", next_=b, cid=a)  # points at b before b exists: legal, FK is deferred
    insert_chunk(tx, fid, 1, "second", prev=a, cid=b)
    tx.execute("SET CONSTRAINTS ALL IMMEDIATE")  # would raise if a link were dangling


def test_dangling_link_is_rejected_at_commit(tx):
    insert_chunk(tx, insert_file(tx), 0, "orphan", next_=uuid.uuid4())
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        tx.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("column,value", [("speaker_id", None), ("text", "   "), ("end_time", 0)])
def test_invariants_are_enforced(tx, column, value):
    fid = insert_file(tx)
    row = {"speaker_id": "SPEAKER_00", "text": "ok", "end_time": 1}
    row[column] = value
    with pytest.raises(psycopg.errors.IntegrityError):
        tx.execute("INSERT INTO chunk (id, audio_file_id, chunk_index, speaker_id, text, start_time, end_time, token_count, "
                   "char_count, language, search_config, search_text) VALUES (%s,%s,0,%s,%s,0,%s,1,2,'en','english',%s)",
                   (uuid.uuid4(), fid, row["speaker_id"], row["text"], row["end_time"], row["text"] or "x"))
