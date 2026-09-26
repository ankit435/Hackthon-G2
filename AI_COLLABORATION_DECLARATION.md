# AI Collaboration Declaration

## Purpose

This project was developed with multiple AI coding agents working alongside the project owner. The agents were used as collaborating engineers: they inspected the repository, implemented bounded tasks, wrote tests, ran verification, recorded results, and handed work off through shared project documentation.

The project owner remains responsible for decisions, credentials, approvals, review of generated content, and the final submission.

## How the agents worked together

The work was divided into clear, non-overlapping responsibilities wherever possible:

| Contributor | Primary work |
|---|---|
| Claude Code | Core retrieval-system implementation and the multilingual Task 17 migration, including the embedding-model/schema transition and re-ingestion. |
| Antigravity | FastAPI endpoints, regression/secondary-metric work, failure analysis, setup verification, and solution documentation. |
| Codex | Structured logging improvements, logging tests, live JSON-event verification, repository review, and coordination support. |

Each agent worked from the repository rather than relying on chat history. The shared project records are `.agent/skills/HANDOFF.md`, `.agent/skills/PROGRESS.md`, and `.agent/skills/AGENT_LOG.md`.

## Agent-guidance paths and how they create the application

The `.agent/skills/` directory is not application code. It is the persistent operating manual that lets multiple AI agents create one coherent application across separate sessions.

| Path | Role in the workflow | How agents use it |
|---|---|---|
| `.agent/skills/skiil.md` | Project skill entry point | Tells an agent when this project workflow applies and requires it to begin with the handoff and progress records. It also captures the essential retrieval, API, chunking, search, and dependency rules. |
| `.agent/skills/HANDOFF.md` | Resume contract | Gives the next agent the current implementation state, active task, known traps, required start/end-of-session steps, locked stack, and task-to-plan mapping. |
| `.agent/skills/PROGRESS.md` | Live status and evidence ledger | Records completed, active, blocked, and pending tasks; environment status; measured retrieval results; decisions; known issues; and open questions. Agents update it when facts change. |
| `.agent/skills/AGENT_LOG.md` | Append-only disclosure log | Attributes each session, its decisions, changed files, packages, verification commands, and remaining work. This prevents invisible AI work. |
| `.agent/skills/PLAN.md` | Authoritative build specification | Defines the scope, architecture, approved stack, ingestion stages, hybrid search behavior, FastAPI contract, evaluation plan, task list, and completion criteria. Agents read the sections relevant to their assigned task before editing. |
| `.agent/skills/MULTILINGUAL_UPDATE_PLAN.md` | Task 17 implementation checklist | Breaks multilingual support into M1–M8: language detection, script-aware sentence splitting, multilingual embeddings, per-row keyword configuration, API/result fields, documentation, and per-language evaluation. |
| `.agent/skills/modelChat.md` | Live multi-agent coordination channel | Used only for task coordination: agents declare ownership, list files being actively edited, announce verification, and publish safe handoff/commit points. |

The practical chain is:

```text
PLAN.md defines the product
        ↓
HANDOFF.md selects the next safe task
        ↓
PROGRESS.md records current facts and decisions
        ↓
Agent edits bounded code/test paths
        ↓
Tests and real-path checks provide evidence
        ↓
AGENT_LOG.md + HANDOFF.md preserve the handoff
```

## Complete implementation path map

### 1. Configuration, environment, and database

| Path | Contribution to the app |
|---|---|
| `.env.example` | Documents required environment variables without storing secrets: database URL, Hugging Face access, Whisper/diarization models, embedding model/device, RRF configuration, and log level. |
| `requirements.txt`, `requirements-dev.txt` | Pin the runtime and development dependencies used by the service and its verification tools. |
| `SETUP.md` | Reproducible setup instructions for Python, ffmpeg, PostgreSQL/pgvector, gated models, environment variables, database initialization, ingestion, and testing. |
| `src/api/settings.py` | The single validated, environment-backed configuration object. It reads settings once at the boundary and injects them into services. |
| `db/schema.sql` | Defines `audio_file` and `chunk` storage, pgvector embedding dimensions, full-text-search structures, integrity constraints, GIN/HNSW indexes, and chunk links. |
| `scripts/init_db.py` | Creates or initializes the local `audio_search` database from the schema in an idempotent way. |
| `scripts/verify_env.py` | Checks that required system tools, Python packages, models, database configuration, and embedding dimensions are available. |

### 2. Domain layer: the stable application contract

| Path | Contribution to the app |
|---|---|
| `src/domain/models.py` | Defines the shared data structures: decoded audio, transcripts, speaker turns, chunks, files, branch hits, search results, reference segments, and labeled queries. |
| `src/domain/ports.py` | Defines interfaces for decoding, transcription, diarization, embeddings, file/chunk persistence, and retrieval. Application code depends on these contracts rather than vendor libraries. |
| `src/domain/errors.py` | Defines typed failures with context such as stage, file, query, or configuration information. |

### 3. Application layer: the retrieval pipeline and business logic

| Path | Contribution to the app |
|---|---|
| `src/application/alignment.py` | Assigns transcript words/segments to the diarized speaker turn with deterministic tie-breaking. |
| `src/application/chunking.py` | Merges same-speaker runs, splits sentences deterministically or semantically, preserves timestamps, counts fallbacks, and links adjacent chunks. |
| `src/application/ingest.py` | Orchestrates validation → decode → transcription → diarization → alignment → chunking → embedding → atomic persistence; isolates a failure to one file in a batch. |
| `src/application/fusion.py` | Implements pure weighted Reciprocal Rank Fusion: each branch contributes `weight / (rrf_k + rank)` and results are cut to top-K only after fusion. |
| `src/application/search.py` | Runs keyword and semantic retrieval concurrently, embeds the query once, fuses candidates, hydrates ranked results, validates inputs, and emits structured search events. |
| `src/application/evaluation.py` | Computes recall@k, hit@k, MRR, speaker mapping/accuracy, and latency summaries from the same search path the API exposes. |

### 4. Infrastructure layer: concrete audio, model, database, and dataset adapters

| Path | Contribution to the app |
|---|---|
| `src/infra/audio.py` | Decodes audio into the normalized form needed by the pipeline. |
| `src/infra/whisper.py` | Uses Faster-Whisper to transcribe and detect language, including word timestamps. |
| `src/infra/diarizer.py` | Uses the configured pyannote pipeline to identify the two speakers. |
| `src/infra/embedder.py` | Loads the local sentence-transformer embedding model, counts tokens, and produces vectors used for retrieval and semantic splitting. |
| `src/infra/postgres.py` | Implements durable audio/chunk storage, keyword search, semantic vector search, hydration, and transaction-safe ingest behavior using PostgreSQL and pgvector. |
| `src/infra/text_search.py` | Selects language-specific full-text-search configuration and prepares CJK character-bigram search text where needed. |
| `src/infra/dataset.py` | Loads the golden manifest, corrected references, and labeled query sets for evaluation. |

### 5. API layer: the user-facing service

| Path | Contribution to the app |
|---|---|
| `src/api/container.py` | The composition root: constructs infrastructure adapters and application services, and configures JSON logging once. |
| `src/api/main.py` | FastAPI app with five endpoints: `POST /ingest`, `GET /search`, `GET /search/keyword`, `GET /search/semantic`, and `GET`/`POST /evaluation`. |
| `src/api/__init__.py` | Marks the API package. |

### 6. Scripts: reproducible operations

| Path | Contribution to the app |
|---|---|
| `scripts/ingest.py` | Ingests the golden audio files and prints per-file outcomes while structured logs capture pipeline stages. |
| `scripts/evaluate.py` | Runs the labeled retrieval evaluation and writes a report without changing the evaluation corpus. |
| `scripts/build_query_set.py` | Builds the English keyword/semantic query set from controlled source material. |
| `scripts/correct_reference_timestamps.py` | Produces corrected reference timestamps without mutating the supplied original dataset. |
| `scripts/build_multilingual_dataset.py` | Deterministically generates multilingual references, QA mappings, and the manifest from translations. |
| `scripts/synthesize_multilingual.py` | Synthesizes multilingual audio and records exact timing/checksum metadata. |
| `scripts/measure_secondary_metrics.py` | Measures secondary quality and performance values, including WER/CER, DER, speaker accuracy, latency, and indexing throughput. |

### 7. Dataset and ground truth

| Path or path group | Contribution to the app |
|---|---|
| `dataset/golden_set.json` | The authoritative six-file manifest used for ingest and evaluation. |
| `dataset/audio_01_rate_limiter.*` through `dataset/audio_06_video_streaming.*` | Golden English audio conversations and their supplied reference metadata. |
| `dataset/audio_07_distributed_cache.*` through `dataset/audio_10_multiregion_db.*` | Preserved source files outside the chosen golden set; they are not silently included through directory globbing. |
| `dataset/reference_corrected/*.json` | Derived timestamp-corrected references used for reliable evaluation while originals remain immutable. |
| `dataset/PROVENANCE.md` | Source checksums, dataset validation findings, and known data defects. |
| `dataset/all.json` | Original QA source material; supporting quotes are resolved to reference segments rather than trusting defective timing fields. |
| `dataset/queries/en.source.json`, `dataset/queries/en.json`, `dataset/queries/en.review.md` | English evaluation sources, generated query set, and human-review record. |
| `dataset/multilingual/translations/{es,hi,zh}/*.txt` | Segment-aligned translation inputs for Spanish, Hindi, and Chinese. |
| `dataset/multilingual/{es,hi,zh}/*.json` | Generated language-specific references and QA records. |
| `dataset/multilingual/manifest.json` | Multilingual corpus inventory, status, durations, and checksums. |

### 8. Tests: how AI work is checked rather than assumed

| Test path | What it verifies |
|---|---|
| `tests/data/test_dataset_integrity.py` | Golden-set checksums, durations, corrected timestamps, segment integrity, and QA quote resolution. |
| `tests/data/test_multilingual_dataset.py` | Translation alignment, reproducible generated data, language/script checks, manifest integrity, and synthesis metadata. |
| `tests/unit/test_alignment.py` | Speaker-alignment edge cases and deterministic tie-breaking. |
| `tests/unit/test_chunking.py`, `tests/unit/test_chunking_qa.py` | Sentence splitting, merge/split boundaries, fallback behavior, links, speaker purity, and regression invariants. |
| `tests/unit/test_fusion.py`, `tests/unit/test_search_service.py` | Correct RRF mathematics, candidate depth, branch reuse, hydration, query validation, weights, and search events. |
| `tests/unit/test_ingest_service.py`, `tests/unit/test_logging.py` | Failure-isolated ingest behavior, stage/per-file/batch events, and JSON log formatting. |
| `tests/unit/test_evaluation_metrics.py` | Hand-computed metric behavior, coverage rules, ranking, speaker mapping, and percentiles. |
| `tests/unit/test_api.py`, `tests/unit/test_settings.py`, `tests/unit/test_architecture.py` | API contracts, configuration validation, and inward-only layer dependencies. |
| `tests/unit/test_text_search.py` | Per-language text-search preparation and CJK-bigram behavior. |
| `tests/integration/test_schema.py`, `tests/integration/test_postgres_repository.py`, `tests/integration/test_search_repository.py` | Real PostgreSQL schema, pgvector, indexes, full-text search, persistence, and repository behavior. |
| `tests/eval/test_retrieval.py` | End-to-end retrieval evaluation using the graded fused `/search` path. |

## Coordination protocol

- Agents read the handoff and progress records before editing code.
- Work was assigned by numbered task, with explicit file ownership for higher-risk concurrent changes.
- The shared `.agent/skills/modelChat.md` file is used only for task coordination: announcing active work, file boundaries, clean commit points, and handoffs.
- Agents avoid editing another agent's active files, and do not pull, merge, or commit shared work without first coordinating when the worktree is active.
- The repository is the source of truth. If notes and code disagree, the code is inspected and the records are corrected.
- Existing tracking history is preserved: agents append or update it rather than recreating it.

## Engineering and verification standard

AI-generated changes are not considered complete merely because code was written. Each task is expected to include, where applicable:

1. Focused unit and integration tests.
2. A full test-suite run when the shared environment is available.
3. Real-path verification for important behaviors, such as a live search or a real ingest.
4. Recorded evidence, limitations, and any unresolved blocker.
5. A clean, coordinated commit before a task is marked fully complete.

This approach is especially important for this project because retrieval quality, timestamps, speaker attribution, multilingual behavior, and measured latency can appear plausible even when an implementation is incorrect.

## Transparency and limits

AI agents accelerated implementation and review, but they did not replace human judgment. In particular:

- Generated multilingual translations remain subject to human language review.
- Evaluation thresholds are not changed simply to make a result pass.
- Measured misses, warnings, and known limitations are documented rather than hidden.
- Secrets, credentials, and user approvals remain outside the agents' authority.

## Declaration

We declare that this project was created through a transparent human-and-AI collaboration. Multiple agents contributed specialized, reviewed work in parallel while following shared task boundaries, persistent handoffs, testing requirements, and explicit coordination practices. The final project should be judged on its code, tests, measured results, documentation, and disclosed limitations—not on an unqualified claim of fully autonomous or fully manual development.
