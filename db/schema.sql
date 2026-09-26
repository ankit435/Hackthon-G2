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
    created_at     timestamptz NOT NULL DEFAULT now(),
    -- The query side MUST parse with this same 'english' configuration (infra, TEXT_SEARCH_CONFIG).
    -- A mismatch produces lexemes by different rules and matches vanish with no error.
    -- Generated, so stemming is identical for every row by construction; to_tsvector keeps
    -- positions, which cover-density ranking (ts_rank_cd) needs.
    text_search    tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, text)) STORED,
    CHECK (end_time > start_time),
    UNIQUE (audio_file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunk_text_search_gin ON chunk USING gin (text_search);

-- HNSW needs no training step, so it is valid on an empty table and stays correct as
-- files are ingested incrementally (Q10). m / ef_construction are pgvector's defaults,
-- recorded explicitly; query-time ef_search is the AUDIO_SEARCH_HNSW_EF_SEARCH setting.
CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw ON chunk
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS chunk_audio_file_id ON chunk (audio_file_id);
