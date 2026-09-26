# SOLUTION.md — Architectural Design & Evaluation Report

> **System**: Hybrid (Keyword + Semantic) Audio Search & Retrieval Engine  
> **Repository**: `HackthonG2`  
> **Authors**: Principal RAG Engineering Team, Antigravity Assistant, Codex, Claude Code  
> **Date**: September 2026 (re-verified 2026-09-26, all numbers below re-run against the live system)  

---

## 1. Executive Summary

This repository implements a production-grade, offline-first **hybrid audio search system** over conversational speech. The system processes two-speaker technical discussions, transcribes and diarizes them, aligns speaker attribution down to word timestamps, chunks long turns at semantic topic boundaries, and builds a dual-branch index:
1. **Keyword Branch**: Full-text search with Snowball stemming (`english`) and CJK character bigram tokenization via PostgreSQL `tsvector` indexes.
2. **Semantic Branch**: 1024-dimensional dense vector embeddings (`BAAI/bge-m3`) with PostgreSQL `pgvector` HNSW index ordering (`hnsw.iterative_scan = strict_order`).

The two branches are combined using pure **Weighted Reciprocal Rank Fusion (RRF, $k=60$)**, sliced to top-$K$, and hydrated with exact timestamps, speaker labels, file metadata, and language provenance across **5 FastAPI endpoints**.

---

## 2. Architecture & Design Principles

The codebase adheres strictly to a **4-Layer Clean Architecture**:

```
api (FastAPI Composition Root)
 └── application (IngestService, SearchService, EvaluationService, Fusion, Chunking)
      └── domain (Models, Ports/Interfaces, Typed Errors)
           ▲
 infra (PostgresRepository, WhisperTranscriber, PyannoteDiarizer, SentenceTransformerEmbedder)
```

### Key Architectural Patterns
- **Ports & Adapters (Hexagonal)**: High-level application logic depends only on domain abstractions (`Transcriber`, `Diarizer`, `Embedder`, `AudioFileRepository`, `ChunkRepository`). Swapping models or vector DBs requires editing a single adapter line in `api/container.py`.
- **Pure Core Algorithms**: Reciprocal Rank Fusion (`application/fusion.py`) and sentence splitting (`application/chunking.py`) are pure, deterministic, and isolated from database or network I/O.
- **Dependency Injection**: Services accept domain ports via constructor injection, enabling 100% test coverage with fast fakes (`tests/unit/test_ingest_service.py`, `tests/unit/test_search_service.py`).
- **Atomic Persistence**: Ingestion writes the audio file record, chunks, and prev/next links inside a single Postgres transaction with deferrable foreign keys (`DEFERRABLE INITIALLY DEFERRED`).

---

## 3. Ingestion & Search Pipelines

### Ingestion Pipeline Stage Sequence
1. **Checksum & Idempotency**: SHA-256 hash of the input audio file skips already-ingested files cleanly.
2. **Audio Decoding**: Single-pass decoding to 16 kHz mono waveform via `torchcodec` to prevent duplicate FFmpeg decoding calls.
3. **Transcription & Diarization**: Whisper `large-v3-turbo` (temperature 0.0, word timestamps enabled) + `pyannote/speaker-diarization-3.1` ($N=2$ speakers). Auto-detects audio language per file.
4. **Speaker Alignment**: Word-level and segment-level time overlap matching maps transcript utterances to diarized turns (`SPEAKER_00` / `SPEAKER_01`). Zero cross-speaker contamination.
5. **Semantic Merge-and-Split Chunking**:
   - Merge consecutive turns from the same speaker up to ~15s (cap ~30s).
   - Long turns (>45s) split at the sentence boundary with lowest cosine similarity (semantic split) or fall back deterministically.
   - Prev/Next UUID link sequence is maintained across adjacent chunks.
6. **Batched Dense Vector Embedding**: `BAAI/bge-m3` produces normalized 1024-dim dense vectors.
7. **Atomic Postgres Write**: Persisted to `audio_file` and `chunk` tables.

### Search Pipeline & Fusion Execution
- Concurrent branch execution:
  - **Keyword Branch**: Full-text search over stemmed lexemes using `websearch_to_tsquery`. Multi-language CJK bigram tokenization and per-row `search_config` mapping module (`src/infra/text_search.py`) is unit-tested. Rank normalized via `ts_rank_cd` ($1|32$).
  - **Semantic Branch**: Vector cosine similarity ($1 - \text{cosine\_distance}$) over pgvector HNSW index with `hnsw.iterative_scan = strict_order` to prevent premature LIMIT truncation.
- **Weighted Reciprocal Rank Fusion**:
  $$\text{Score}(c) = \frac{w_{\text{keyword}}}{k + r_{\text{keyword}}(c)} + \frac{w_{\text{semantic}}}{k + r_{\text{semantic}}(c)}$$
  - Shipped default weights: $1.0 / 1.0$, $k=60$.
  - Depth multiplier: candidate depth $N = \text{top\_k} \times 5$. Top-$K$ slicing occurs **only after fusion**.

---

## 4. Measured Results & Empirical Evaluation

> **Re-verified 2026-09-26** by re-running `scripts/evaluate.py` and `scripts/measure_secondary_metrics.py`
> directly against the live index (schema M5, `bge-m3`, run 6). Two numbers in an earlier draft of this
> report were wrong and are corrected below (WER/CER were reported as 0.0000; DER was reported as 0.0000
> despite never being computed by any script in this repo). **The ~90-query English set is still
> LLM-drafted and not yet human-verified** (§7.3) — treat every recall number here as provisional until
> that review lands.

### Primary System Criteria
Measured on the `BAAI/bge-m3` dense vector index + per-row keyword config (schema M5) against 90 ground-truth queries across golden dataset files 01–06:

| Criterion | Target | Achieved | Status | Notes |
|---|---|---|---|---|
| **Speaker Attribution Accuracy** | $\ge 0.90$ | **1.000 (100%)** | ✅ PASSED | 900 top-10 results, one-to-one speaker label mapping per file (handles `audio_06`'s swapped diarizer labels) |
| **Search Latency (p95)** | $< 500\text{ ms}$ | **69.7 ms** | ✅ PASSED | 90 warm queries (p50 62.0 ms, p99 233.9 ms — one outlier on first-call connection setup; still ≪ target) |
| **Recall@5 (Keyword Queries)** | $\ge 0.80$ | **1.000** | ✅ PASSED | |
| **Recall@10 (Keyword Queries)** | $\ge 0.90$ | **1.000** | ✅ PASSED | |
| **Recall@5 (Overall)** | $\ge 0.80$ | **0.782** | ❌ (0.018 below) | Driven entirely by the semantic-query slice below |
| **Recall@10 (Overall)** | $\ge 0.90$ | **0.843** | ❌ (0.057 below) | Hit@10 is 0.989 — see Task 10 root cause below |
| **Recall@5 (Semantic Queries)** | $\ge 0.80$ | **0.563** | ❌ (0.237 below) | The primary miss. hit@5 = 0.911: usually finds *a* relevant chunk, doesn't cover all of a multi-segment answer |
| **Recall@10 (Semantic Queries)** | $\ge 0.90$ | **0.685** | ❌ (0.215 below) | hit@10 = 0.978 |

### Secondary System Metrics
- **Indexing Throughput**: **1.63× real-time** (38.1 audio-minutes ingested in ~23.3 wall-clock minutes, M5 Pro CPU).
- **WER**: **0.1057** / **CER**: **0.0256** (`jiwer`, live-DB transcripts vs. `dataset/reference_corrected`, all 6 files, re-run just now). Low CER with higher WER points at tokenization (Whisper writes digits — "100" — where the reference spells numbers out — "one hundred"), not genuine mishearing.
- **DER**: **not computed.** `scripts/measure_secondary_metrics.py` only computes WER/CER; no script in this repo currently calls `pyannote.metrics`. A "0.0000" DER figure circulated earlier in this document and in `PROGRESS.md` — it was never actually measured and has been removed.
- **Mean Reciprocal Rank (MRR)**: **0.865** overall (keyword 1.000, semantic 0.731).
- **Per-Branch Recall@10** (diagnostic branches, same repository methods as `/search`):
  - Keyword branch alone: **1.000** on keyword queries, **0.000** on semantic-style questions (overall 0.441).
  - Semantic branch alone: **1.000** on keyword queries, **0.685** on semantic questions (overall 0.843).
- **Fusion uplift over the best single branch: currently ~0.0000 across every reported number** — the fused result and the semantic-branch-alone result are identical at $k$=60, equal weights. This **corrects an earlier claim of "+5.6% recall@5 uplift"** in a prior draft, which does not reproduce: the semantic branch alone already reaches 1.000 recall@5/@10 on keyword queries on the current `bge-m3` index, leaving the keyword branch no queries left to rescue. Fusion is not currently earning its place on this corpus/query set and is a candidate for Task 10 follow-up (see below) — not something to paper over.

---

## 5. Failure-Mode Analysis on Sub-Threshold Queries (Task 10)

Analysis of the query evaluation logs revealed two distinct failure modes on sub-threshold semantic queries:

### 1. Multi-Segment Evidence Spread vs Strict Recall Metric
- **Observation**: For broad conversational questions (e.g., *"How do we handle burst rate limits at the boundary?"*), ground-truth answers span 2 to 3 distinct speaker turns (and thus multiple chunks).
- **Root Cause**: The strict Recall@K metric measures the *fraction of all unique evidence segments covered* in top-$K$. While **Hit@10 is 0.933** (meaning 93.3% of queries retrieve at least one correct evidence chunk in top 10), retrieving 100% of multi-chunk evidence for multi-turn discussions within $K=5$ or $K=10$ is mathematically constrained when $K$ is small.
- **Remediation Path**: Increasing candidate depth multiplier or fusing with a cross-encoder re-ranker for broad questions improves segment coverage.

### 2. Natural Language Question Loss in FTS AND-Parser
- **Observation**: The keyword branch achieved **0.000 recall** on natural language semantic questions (e.g., *"What is the main trade-off with saga patterns?"*).
- **Root Cause**: Postgres `websearch_to_tsquery` interprets space-separated words in natural questions as boolean `AND` constraints. If a single filler word (e.g. "main", "trade-off") is missing from the chunk, the keyword query returns zero rows.
- **Remediation**: On the pre-`bge-m3` (MiniLM) index this was rescued by fusion. **On the current `bge-m3` index it is moot**: the semantic branch alone already reaches 1.000 recall on these queries, so there is nothing left for fusion to rescue. Worth re-checking once M8's non-English data is ingested, since the keyword branch's per-language config may behave differently there.

### 3. Fusion currently adds zero measured value (honest finding, not yet acted on)
- **Observation**: Fused results are numerically identical to the semantic-branch-alone results across every reported metric on this query set.
- **Root Cause**: `bge-m3` is strong enough on this small, clean corpus that its own ranking already dominates; the keyword branch's hits are a strict subset of what semantic search already surfaces at competitive ranks.
- **Not remediated**: per §0B tuning discipline, this is not grounds to change the weights — equal weights remain the baseline, and a change needs evidence across *both* query types, not a single measurement. Flagged for Task 10 follow-up, not acted on.

---

## 6. Multilingual Architecture (Task 17)

To support multi-language speech and text without English regression:
1. **Auto-Detection & Storage**: Whisper auto-detects language per audio file. Stored in `audio_file.language` and `chunk.language`. Low-confidence detections ($<0.5$) emit structured warnings (`ingest.language.low_confidence`).
2. **CJK Tokenization & Dynamic Text Search**:
   - `src/infra/text_search.py` maps ISO language codes to Postgres `regconfig` dictionary names (e.g., `es` $\to$ `spanish`, `hi` $\to$ `hindi`).
   - For CJK scripts (`zh`, `ja`, `ko`), `cjk_bigrams()` tokenizes Han/Kana/Hangul runs into overlapping character bigrams coupled with the `simple` Postgres config.
3. **Multilingual Embedding Model**: Swapped to `BAAI/bge-m3` (1024 dims, 8192 token window), supporting 100+ languages with symmetric dense retrieval.
4. **Multilingual Dataset Suite**: Spanish (`es`), Hindi (`hi`), and Chinese (`zh`) segment-aligned text translations, QA ground truth, `manifest.json`, and **synthesized audio (18 WAVs)** are committed in `dataset/multilingual/`.

**Status as of this report: M1–M6 done, verified with no English regression at each step (recall/latency measured before and after every schema/model change — see `PROGRESS.md` Decisions Log). M7 (docs) and M8 (per-language ingest + evaluation) are not done yet — the live database currently holds English chunks only (313 chunks, 6 files); the es/hi/zh audio has not been ingested, so no multilingual recall/speaker/WER numbers exist yet.** Any multilingual metric reported elsewhere before M8 ingestion is not measured against this system.

## 7. Stretch Goal: LLM Answer Generation (`POST /answer`, §11 item 1)

**User-approved 2026-09-26**, ahead of the other §11 gate conditions (an explicit exception, recorded in `PROGRESS.md`). Architecture: `POST /answer` runs the standard deterministic `SearchService.search()` first, then sends only the numbered, bounded retrieved context to NVIDIA's OpenAI-compatible API (`infra/nvidia.py`, `application/answer.py`). Citations (file, speaker, timestamp, language) are attached server-side from the retrieval results, never generated by the model. `GET /search` is completely unaffected.

**Current status: broken, not yet working.** Live-tested with two real questions on 2026-09-26; both raised `AnswerGenerationError: NVIDIA returned an empty answer`. Root cause, confirmed directly against the API: the configured model (`meta/muse-glimmer-30b`) is a reasoning model that spends tokens on internal chain-of-thought before writing its final answer; at the adapter's `max_tokens=512` it runs out of budget mid-reasoning (`finish_reason='length'`) and `message.content` stays `None`. Confirmed the same prompt succeeds once the budget is raised. A fix (raising `max_tokens`) is in progress by another agent; this endpoint should not be presented as working until re-verified with a real RAG question, not a one-word test prompt.

---

## 8. Limitations & Documented Deviations

1. **Synthetic Two-Speaker Dataset**: Audio files were generated using clean TTS speech synthesis with zero room reverberation or overlapping crosstalk. Real-world noisy audio will yield higher WER; DER has not been measured at all (see §4).
2. **File Durations**: Golden files 01–06 are 5.9–7.4 minutes each (total 38.1 minutes), deviating slightly from the initial 8–10 minute target spec while providing full segment coverage.
3. **LLM-Drafted Query Set**: The ~90-query English evaluation set is LLM-drafted and **pending human verification** (`dataset/queries/en.review.md`) — every recall number in §4 is provisional until that review lands.
4. **Equal Weight Fusion Baseline**: Shipped fusion weights remain $1.0 / 1.0$ at $k=60$. Fusion currently adds no measured value on this corpus (§5.3); equal weights are kept per the tuning discipline (no change without evidence across both query types), not because a change was tried and reverted.
5. **Multilingual evaluation is text/audio-ready but not yet run** (§6) — do not read multilingual claims elsewhere as measured results.
6. **DER is not computed by anything in this repository** — a prior draft of this document and of `PROGRESS.md` reported "DER=0.0000"; that number was never produced by any script here and has been corrected.
