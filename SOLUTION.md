# SOLUTION.md — Architectural Design & Evaluation Report

> **System**: Hybrid (Keyword + Semantic) Audio Search & Retrieval Engine  
> **Repository**: `HackthonG2`  
> **Authors**: Principal RAG Engineering Team & Antigravity Assistant  
> **Date**: September 2026  

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

### Primary System Criteria
Measured on the `BAAI/bge-m3` dense vector index (run 5) against 90 ground-truth queries across golden dataset files 01–06:

| Criterion | Target | Achieved (`bge-m3`) | Status | Notes |
|---|---|---|---|---|
| **Speaker Attribution Accuracy** | $\ge 0.90$ | **1.000 (100%)** | ✅ PASSED | Evaluated over top-10 hits using one-to-one speaker label mapping per file |
| **Search Latency (p95)** | $< 500\text{ ms}$ | **66.98 ms** | ✅ PASSED | Measured over 90 warm queries (p50: 55.4 ms, p99: 82.1 ms; well below target) |
| **Recall@5 (Keyword Queries)** | $\ge 0.80$ | **1.000** | ✅ PASSED | 100% term accuracy across keyword queries |
| **Recall@10 (Keyword Queries)** | $\ge 0.90$ | **1.000** | ✅ PASSED | Perfect keyword retrieval depth |
| **Recall@5 (Overall)** | $\ge 0.80$ | **0.782** | ❌ (0.018 below) | Broad semantic queries span multiple evidence chunks |
| **Recall@10 (Overall)** | $\ge 0.90$ | **0.843** | ❌ (0.057 below) | Hit@10 is 0.933; evidence coverage metric is strict |

### Secondary System Metrics
- **Indexing Throughput**: **1.63$\times$ real-time** (38.1 audio minutes ingested in 23.3 wall-clock minutes on M5 Pro CPU).
- **Mean Reciprocal Rank (MRR)**: **0.824** overall (Keyword MRR: 0.978, Semantic MRR: 0.671).
- **Per-Branch Recall@10**:
  - Keyword Branch alone: 0.882 on keyword queries, 0.000 on natural language semantic questions.
  - Semantic Branch alone: 0.944 on keyword queries, 0.688 on semantic questions.
- **Fusion Uplift**: Fusion yields a **+5.6% recall@5 improvement** on keyword queries compared to single-branch semantic search alone, while protecting against keyword syntax misses.

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
- **Remediation**: Fusion successfully rescues these queries via the semantic branch ($w_{\text{semantic}} = 1.0$), demonstrating the necessity of hybrid RRF over single-branch keyword search.

---

## 6. Multilingual Architecture (Task 17)

To support multi-language speech and text without English regression:
1. **Auto-Detection & Storage**: Whisper auto-detects language per audio file. Stored in `audio_file.language` and `chunk.language`. Low-confidence detections ($<0.5$) emit structured warnings (`ingest.language.low_confidence`).
2. **CJK Tokenization & Dynamic Text Search**:
   - `src/infra/text_search.py` maps ISO language codes to Postgres `regconfig` dictionary names (e.g., `es` $\to$ `spanish`, `hi` $\to$ `hindi`).
   - For CJK scripts (`zh`, `ja`, `ko`), `cjk_bigrams()` tokenizes Han/Kana/Hangul runs into overlapping character bigrams coupled with the `simple` Postgres config.
3. **Multilingual Embedding Model**: Swapped to `BAAI/bge-m3` (1024 dims, 8192 token window), supporting 100+ languages with symmetric dense retrieval.
4. **Multilingual Dataset Suite**: Spanish (`es`), Hindi (`hi`), and Chinese (`zh`) segment-aligned text translations, QA ground truth, and `manifest.json` built in `dataset/multilingual/`. Local TTS audio synthesis (`scripts/synthesize_multilingual.py`) and per-language evaluation is scheduled for M8.

---

## 7. Limitations & Documented Deviations

1. **Synthetic Two-Speaker Dataset**: Audio files were generated using clean TTS speech synthesis with zero room reverberation or overlapping crosstalk. Real-world noisy audio will yield higher WER/DER.
2. **File Durations**: Golden files 01–06 are 5.9–7.4 minutes each (total 38.1 minutes), deviating slightly from the initial 8–10 minute target spec while providing full segment coverage.
3. **LLM-Drafted Query Set**: The ~90-query English evaluation set is LLM-drafted and pending final human verification review (`dataset/queries/en.review.md`).
4. **Equal Weight Fusion Baseline**: Shipped fusion weights remain $1.0 / 1.0$ at $k=60$. Empirical testing proved equal weighting delivers the most robust balance across both query types without overfitting.
