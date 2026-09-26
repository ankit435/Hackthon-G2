# MULTILINGUAL_UPDATE_PLAN.md — Task 17 implementation checklist


> **Self-contained.** An agent doing Task 17 works from this file alone. It
> does not need to re-read `PLAN.md`. The rationale is in `PLAN.md` §7B. The
> general rules still apply, and the short version is in §0 below.
>
> Line numbers refer to the code at commit `43abd98`. If a line has moved,
> find it by the quoted text. The repo wins over this file.
> Update the checkboxes and `PROGRESS.md` as you go.


---


## 0. Rules that still apply (short form)

- Work in `.venv`. Pin every new package with `==`, log it in `PROGRESS.md` → Installed Packages, and update `SETUP.md` (§4B).
- **Done = code + tests pass + run on real data + committed.**
- **English must not regress.** Record English recall@5/@10 and p95 **before** the first step and after every step, in `PROGRESS.md` → Measured Results.
- Layers point inward: `api → application → domain`. Only `infra` imports models or runs SQL, and only `api/container.py` wires them.
- Never stem in application code. Never silently fall back to a default: every fallback logs a WARNING and is counted.
- `/search` stays deterministic, with no language or weight parameters.


## 1. Final decisions (do not reopen)

| Item | Decision |
|---|---|
| Languages | **Any.** Whisper auto-detects, one language per file. No whitelist |
| Transcriber | `large-v3-turbo` (already multilingual). Remove forced `language="en"`. Optional override `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE` (blank = auto) |
| Embedder | **`BAAI/bge-m3`**, dense, expected **1024 dims / 8192 tokens**. **Measure both on the loaded model first.** Symmetric (no prefixes), MIT, not gated, ~2.3 GB. Suits an Apple Silicon MacBook Pro with 24 GB. Device `cpu` by default, `mps` allowed |
| Keyword branch | Per-row config: `chunk.search_config` mapped from the language. `chunk.search_text` = CJK-bigram(`text`). Generated column `to_tsvector(search_config, search_text)`. The query is bigram-processed with the same function and parsed once per config present |
| CJK (zh/ja/ko) | `simple` config plus **character bigrams**, no Postgres extension |
| Unmapped language | `simple` + WARNING + count, **never** `english` |
| Evaluation languages | en + **es, hi, zh**, as translations of golden files 01–06 |
| Thresholds | recall@5 ≥ 0.80, recall@10 ≥ 0.90, speaker ≥ 0.90: **per language AND overall**. Cross-lingual is reported, not gated. p95 < 500 ms on the full corpus |
| Latency fallback | If p95 fails: try `mps`, then `intfloat/multilingual-e5-base` (needs `query:`/`passage:` prefixes, so an Embedder port change). Record the before/after |


## 2. Step order

1. ☑ **Baseline** (2026-09-26, provisional pending query-set verification): overall r@5 0.778 / r@10 0.811, keyword 0.956 / 0.956, semantic 0.600 / 0.667, speaker 1.000, p95 15.5 ms. MiniLM, 313 chunks. Report: `logs/eval-en-20260926-125019.json` (gitignored); numbers in PROGRESS.md. **English recall and p95 on the current build.** This needs Tasks 4 and 5 working. If Task 5 isn't done, record WER/DER/speaker accuracy as the baseline instead.
2. ☐ **M1** language detection + storage (§3.1–3.3)
3. ☐ **M3** sentence splitter (§3.4)
4. ☐ **M4** embedder → bge-m3, `vector(1024)`, re-ingest (§3.5)
5. ☐ **M5** per-row keyword config + bigrams, **together with Task 5's keyword branch** (§3.6)
6. ☐ **M6** API, settings, docs (§3.7–3.8)
7. ☐ **M8** translated dataset + per-language evaluation (§4)


## 3. Code changes, file by file

### 3.1 `src/infra/whisper.py` — M1
- ☐ **Line 15**: replace the docstring bullet `language="en" is a dataset fact…` with *"language is auto-detected unless forced by settings; detection uses the first 30 s, so there is one language per file."*
- ☐ **Line 18** `__init__`: add a `language: str | None` parameter and store it.
- ☐ **Line 27**: `language="en"` → `language=self._language` (None = detect). Keep `beam_size=5, temperature=0.0, condition_on_previous_text=False`.
- ☐ **Line 27–29**: stop discarding `_info`. Return `info.language` and `info.language_probability` with the segments (see port change 3.2).

### 3.2 `src/domain/models.py` + `src/domain/ports.py` — M1/M6
- ☐ `models.py`: add a dataclass `Transcript(segments: list[TranscriptSegment], language: str, language_probability: float)`.
- ☐ `models.py:58` `AudioFile`: add `language: str` and `language_probability: float`.
- ☐ `models.py:68` `Chunk`: add `language: str`.
- ☐ `models.py:98` `SearchResultItem`: add `language: str`.
- ☐ `ports.py:29-30` `Transcriber.transcribe` → returns `Transcript`. Update the docstring.
- ☐ The `Embedder` port (`ports.py:41`) stays **unchanged**, because bge-m3 is symmetric.

### 3.3 `src/application/ingest.py` — M1
- ☐ **Line 116–117** transcribe stage: take `transcript.segments`. Log `language` + `language_probability` on the stage end. If `language_probability < LANGUAGE_CONFIDENCE_WARN` (named constant `= 0.5`), log a WARNING `ingest.language.low_confidence`. Record it in `IngestOutcome` (new fields `language`, `language_probability`).
- ☐ **Line 132** `AudioFile(...)`: pass the language and its probability.
- ☐ **Line 141** `Chunk(...)`: pass `language=transcript.language`.
- ☐ Unit test (`tests/unit/test_ingest_service.py`): the stub transcriber returns `es` and the language reaches `AudioFile` and every `Chunk`. A low-probability run logs the warning.

### 3.4 `src/application/chunking.py` — M3
- ☐ **Line 31** `_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")` → split after `.!?` + whitespace, after `。！？` with **optional** whitespace, and after `।` `॥` `؟` `۔` + whitespace. Suggested pattern: `r"(?<=[.!?।॥؟۔])\s+|(?<=[。！？])\s*"`, filtering empty parts (line 117 already does).
- ☐ **Line 108** `sentences()` docstring: note that character-length apportionment is a per-script approximation.
- ☐ Tests (`tests/unit/test_chunking.py`): split Chinese `"你好。我们开始吧！"` → 2, Hindi `"यह पहला है। यह दूसरा है।"` → 2, Arabic `؟`, English unchanged (the existing tests must still pass). Times still sum exactly to the segment duration.

### 3.5 Embedder → `BAAI/bge-m3` — M4
- ☐ **First, measure:** load `SentenceTransformer("BAAI/bge-m3")` in the venv and record `get_embedding_dimension()` and `max_seq_length` in `PROGRESS.md`. **If dim ≠ 1024, use the measured value everywhere below.**
- ☐ `src/api/settings.py:35` `embedding_model` default → `"BAAI/bge-m3"`. Add `embedding_device: Literal["cpu","mps","cuda"] = "cpu"` and `transcription_language: str | None = None` (validator: blank → None; a code must be one of Whisper's language codes, else `ValueError` → `ConfigurationError`).
- ☐ `src/api/container.py:39` `SentenceTransformerEmbedder(settings.embedding_model, device=settings.embedding_device)`. **Line 42** `FasterWhisperTranscriber(settings.whisper_model, language=settings.transcription_language)`.
- ☐ `src/infra/embedder.py:27` `_encode`: keep `normalize_embeddings=True`. No prefixes.
- ☐ `db/schema.sql:23-24` comment + `embedding vector(384)` → `vector(1024)` with comment `-- 1024 = BAAI/bge-m3`.
- ☐ `scripts/verify_env.py:11` `EMBEDDING_DIM = 384` → `1024`. **Line 50**: load the model from settings/env instead of the hard-coded MiniLM name.
- ☐ `tests/integration/test_schema.py:48` `test_embedding_column_is_vector_384` → `..._1024`. **Line 88** wrong-dimension test: use 1023.
- ☐ `.env.example:15` → `AUDIO_SEARCH_EMBEDDING_MODEL=BAAI/bge-m3`. Add `AUDIO_SEARCH_EMBEDDING_DEVICE=cpu` and `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE=` with comments.
- ☐ `requirements.txt`: no new package is expected (sentence-transformers already pinned). If the model needs a newer `transformers`, pin it and log it.
- ☐ Drop and recreate the DB (`scripts/init_db.py`), re-ingest the golden set, and record English recall/p95/throughput before and after.

### 3.6 Keyword branch per row — M5 (with Task 5)
- ☐ **New `src/infra/text_search.py`** (infra only):
  - `ISO_TO_CONFIG: dict[str, str]`: `ar arabic, ca catalan, da danish, de german, el greek, en english, es spanish, eu basque, fi finnish, fr french, ga irish, hi hindi, hu hungarian, hy armenian, id indonesian, it italian, lt lithuanian, ne nepali, nl dutch, no norwegian, pt portuguese, ro romanian, ru russian, sr serbian, sv swedish, ta tamil, tr turkish, yi yiddish, zh simple, ja simple, ko simple`.
  - `config_for(language, available: set[str]) -> str`: return the mapped config if the server has it. Otherwise return `simple` + WARNING `search.config.fallback` (with the language) + a counter.
  - `cjk_bigrams(text) -> str`: rewrite each run of Han `一-鿿㐀-䶿`, Hiragana `぀-ゟ`, Katakana `゠-ヿ` and Hangul `가-힯` into space-separated overlapping bigrams (a 1-character run stays as is). Everything else is unchanged. **It must be the identity on non-CJK text**, so a unit test asserts that on the English fixtures.
- ☐ `src/infra/postgres.py:14-17`: replace `TEXT_SEARCH_CONFIG = "english"` with an import of the module above. Keep the "why" comment, now worded as *per row*.
- ☐ `db/schema.sql:15-35` `chunk` table: add `language text NOT NULL`, `search_config regconfig NOT NULL`, `search_text text NOT NULL`. **Line 35** → `text_search tsvector GENERATED ALWAYS AS (to_tsvector(search_config, search_text)) STORED`. Add a `CHECK (btrim(search_text) <> '')`. Add an index `chunk_search_config` on `(search_config)`.
- ☐ `db/schema.sql:6-12` `audio_file`: add `language text NOT NULL`, `language_probability double precision NOT NULL CHECK (language_probability BETWEEN 0 AND 1)`.
- ☐ `src/infra/postgres.py:19` `_CHUNK_COLUMNS` + **line 54** INSERT: add `language, search_config, search_text`. `search_text = cjk_bigrams(c.text)`. `search_config = config_for(c.language, available)`, where `available` comes from `SELECT cfgname FROM pg_ts_config`, cached per connection. **Line 49** audio_file INSERT: add `language, language_probability`.
- ☐ `src/infra/postgres.py:71` `keyword_search` (Task 5): `q = cjk_bigrams(query)`. For each `cfg` in `SELECT DISTINCT search_config FROM chunk`: `SELECT id, ts_rank_cd(text_search, websearch_to_tsquery(cfg, q), 32) AS s FROM chunk WHERE search_config = cfg AND text_search @@ websearch_to_tsquery(cfg, q) ORDER BY s DESC LIMIT n`. Merge all passes by `s` descending, keep the top `limit`, and assign 1-based ranks. Break ties by `id` for determinism. One round trip is fine via `UNION ALL`.
- ☐ `hydrate` (**line 77**): return `language`.
- ☐ Tests, `tests/integration/test_schema.py`:
  - **Line 54** `test_generated_tsvector_uses_the_query_side_config` → assert the expression is `to_tsvector(search_config, search_text)`.
  - **Line 68** stemming test: add a Spanish case (`search_config='spanish'`, index "archivando", query "archivado" → match).
  - Add a Chinese bigram case (index "限流器很重要", query "限流器" → match; query "器很流" → no phrase match).
  - Add an unmapped language → `simple` + WARNING case.
  - **Line 77** mismatch test: keep it (English vs `simple`).
- ☐ Unit tests `tests/unit/test_text_search.py`: the bigram function (CJK, mixed text, identity on English/Spanish/Hindi, a single character) and `config_for` (mapped, missing on server, unmapped).
- ☐ `tests/unit/test_architecture.py`: still passes (the new module is in infra).

### 3.7 API / search results — M6 (Task 11)
- ☐ Response models include `language` per hit. `/search` gets **no** language parameter.
- ☐ `/evaluation` returns metrics per language plus overall plus cross-lingual, and echoes the embedding model name.

### 3.8 Docs — M7
- ☐ `SETUP.md:73`: MiniLM ~90 MB → bge-m3 ~2.3 GB download. Expect a slow first run.
- ☐ `SETUP.md:97-98`: `vector(1024)`; the tsvector is `to_tsvector(search_config, search_text)`.
- ☐ `SETUP.md:115` expected verify output → `embedder: dim=1024, max_seq_length=<measured>`.
- ☐ `SETUP.md:131-132` troubleshooting: dimension message 1024. The config check becomes per language: `SELECT to_tsvector('spanish','archivando') @@ websearch_to_tsquery('spanish','archivado');` → `t`. Add a row: "non-English keyword search finds nothing" → check `search_config` on the rows and the WARNING count.
- ☐ `SETUP.md` §5 table: add `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE` and `AUDIO_SEARCH_EMBEDDING_DEVICE`.
- ☐ `SOLUTION.md` (Task 14): supported languages, the bigram approach for CJK, per-script apportionment, per-language results, the English before/after, and translated synthetic data as a limitation.


## 4. Evaluation data — M8

- ☐ **Translate** `dataset/reference_corrected/audio_0{1..6}_*.json` segment by segment into **es, hi, zh**. Keep the segment count, order and speaker; only `text` changes. LLM-drafted, **human-verified**. Record who verified in `AGENT_LOG.md`.
- ☐ **Synthesise** two-speaker audio per translated file with a local **dev-only** TTS. Candidate: **Kokoro-82M** (Apache-2.0, runs on a Mac, has es/hi/zh voices). Use two distinct voices per file. Pin it in `requirements-dev.txt`, and never import it from `src/`. Verify the voice list on install. If the user supplies the original generator (Q20), use that instead. Write the reference start/end times **from the synthesis itself** (exact), mono WAV.
- ☐ Layout: `dataset/multilingual/<lang>/<audio_id>.{wav,json}`, plus `dataset/multilingual/<lang>/qa.json` with the questions, answers and supporting context translated. Evidence maps **by segment index** (index *i* is the same utterance in every language).
- ☐ `dataset/golden_set.json`: add `"language": "en"` to the existing 6 entries, plus 18 entries (6 × es/hi/zh) with sha256. `dataset/PROVENANCE.md`: add a section for the translation method, TTS engine and version, voices, and checksums.
- ☐ `tests/data/test_dataset_integrity.py`: the translated files have the same segment count and speakers as their English source, the durations match the WAVs, and the checksums match.
- ☐ Query set (Task 6): translate the ~90 English queries per language (same-language slices). Run the English queries against es/hi/zh files for the cross-lingual slice. Ground truth = the chunks that cover the mapped segment index.
- ☐ Metrics (Tasks 7, 9): recall@5/@10, MRR, speaker accuracy and WER/CER per language, plus overall and cross-lingual. Use Whisper's basic normalizer for es/hi/zh, and **CER as the primary transcription metric for zh**. Gate per language and overall (§1).
- ☐ Ingest cost: 18 more files (~2 h audio) on CPU. Record throughput per stage.


## 5. Done criteria for Task 17

- ☐ All the tests above pass, and the whole existing suite is green.
- ☐ English recall/speaker/p95 are recorded before and after with **no regression**.
- ☐ es, hi and zh are ingested. Every language meets the thresholds **per language and overall**, or each miss has a documented root cause (§10.5 of the plan; never lower a threshold).
- ☐ `PROGRESS.md` (Task 17 → Done, measured results, Installed Packages, Decisions Log), `HANDOFF.md` §4 and `AGENT_LOG.md` are updated, and everything is committed.
