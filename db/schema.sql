-- Audio Hybrid Search schema (PLAN.md §8). Idempotent: safe to re-apply.
-- Apply:  python scripts/init_db.py   (creates the database if missing, then runs this file)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS audio_file (
    id               uuid PRIMARY KEY,
    file_name        text NOT NULL,
    file_path        text NOT NULL,
    checksum         text NOT NULL UNIQUE,          -- sha256; idempotency key for ingest
    duration_seconds double precision NOT NULL CHECK (duration_seconds > 0),
    -- Whisper detects one language per file (PLAN.md §7B); the probability is kept so
    -- low-confidence detections stay visible after ingest.
    language         text NOT NULL CHECK (btrim(language) <> ''),
    language_probability double precision NOT NULL CHECK (language_probability BETWEEN 0 AND 1),
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk (
    id             uuid PRIMARY KEY,
    audio_file_id  uuid NOT NULL REFERENCES audio_file(id) ON DELETE CASCADE,
    chunk_index    integer NOT NULL CHECK (chunk_index >= 0),
    speaker_id     text NOT NULL,                   -- never NULL: alignment always assigns a speaker
    text           text NOT NULL CHECK (btrim(text) <> ''),
    start_time     double precision NOT NULL CHECK (start_time >= 0),
    end_time       double precision NOT NULL,
    -- 1024 = BAAI/bge-m3 (PLAN.md §7B, M4; measured on the loaded model). Changing the embedding
    -- model means changing this and re-ingesting.
    embedding      vector(1024),
    -- Links are written in the same transaction as their targets, so the FK checks are deferred to commit.
    prev_chunk_id  uuid REFERENCES chunk(id) DEFERRABLE INITIALLY DEFERRED,
    next_chunk_id  uuid REFERENCES chunk(id) DEFERRABLE INITIALLY DEFERRED,
    token_count    integer NOT NULL CHECK (token_count > 0),
    char_count     integer NOT NULL CHECK (char_count > 0),
    language       text NOT NULL CHECK (btrim(language) <> ''),  -- the file's detected language
    -- Per-row keyword config (PLAN.md §7B, M5): mapped from `language` by infra.text_search.config_for,
    -- e.g. 'spanish' for es, 'simple' for zh/ja/ko or any language with no Postgres config. The query
    -- side MUST parse with the SAME config a row was indexed with (infra.text_search, not a single
    -- shared constant any more) — a mismatch produces lexemes by different rules and matches vanish
    -- with no error. Generated, so stemming is identical for every row by construction; to_tsvector
    -- keeps positions, which cover-density ranking (ts_rank_cd) needs.
    search_config  regconfig NOT NULL,
    -- `text` after infra.text_search.cjk_bigrams: CJK runs (Han/Kana/Hangul) rewritten as space-
    -- separated overlapping bigrams, since simple/CJK configs have no word segmenter and would
    -- otherwise index a whole run as one unsearchable token. Identity for every other script.
    search_text    text NOT NULL CHECK (btrim(search_text) <> ''),
    created_at     timestamptz NOT NULL DEFAULT now(),
    text_search    tsvector GENERATED ALWAYS AS (to_tsvector(search_config, search_text)) STORED,
    CHECK (end_time > start_time),
    UNIQUE (audio_file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunk_text_search_gin ON chunk USING gin (text_search);
-- Lets keyword_search's per-config UNION ALL pass restrict to one config's rows before the GIN
-- probe, so each pass's websearch_to_tsquery(cfg, ...) stays a per-scan constant the planner can use.
CREATE INDEX IF NOT EXISTS chunk_search_config ON chunk (search_config);

-- HNSW needs no training step, so it is valid on an empty table and stays correct as
-- files are ingested incrementally (Q10). m / ef_construction are pgvector's defaults,
-- recorded explicitly; query-time ef_search is the AUDIO_SEARCH_HNSW_EF_SEARCH setting.
CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw ON chunk
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS chunk_audio_file_id ON chunk (audio_file_id);
