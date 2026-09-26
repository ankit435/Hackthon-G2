# SETUP — from a fresh clone to a working system

> **Draft (Task 2).** Steps 6–7 grow as the schema (Task 3) and the API (Task 11)
> land. They are finalised and verified on a clean clone in Task 13.

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| **Python** | **3.12** exactly | torch / pyannote.audio 4 / faster-whisper wheels are verified on 3.12. 3.14 is not yet safe for this stack, and 3.9 is too old (pyannote needs ≥ 3.10) |
| **ffmpeg** | any recent (verified with 9.0.2) | Audio decoding for torchcodec (pyannote). **The most common first-run failure.** |
| **PostgreSQL** | 16+ (verified with 18.6) | Storage, full-text search |
| **pgvector** | 0.8+ (verified with 0.8.6) | Vector column + HNSW index |

macOS (Homebrew):
```bash
brew install python@3.12 ffmpeg postgresql@18 pgvector
brew services start postgresql@18
```

Linux (Debian/Ubuntu):
```bash
sudo apt install python3.12 python3.12-venv ffmpeg postgresql postgresql-18-pgvector
# (replace 18 with your Postgres major version)
```

## 2. Virtual environment

Everything runs inside `.venv/` at the repo root. **Never install into the system interpreter.**

macOS / Linux:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```
Windows (PowerShell):
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # tests + WER/CER/DER scoring (includes runtime)
```
The torch download is large (several hundred MB).

## 4. ⚠️ Hugging Face gated model access — do not skip

Speaker diarization uses `pyannote/speaker-diarization-3.1`, which is **gated**.
**This is the single most likely reason a fresh clone fails.**

1. Create or log in to a Hugging Face account.
2. Open **both** pages and accept the user conditions on each:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0 (the pipeline loads this internally, so accepting only the first is not enough)
3. Create a **read** access token at https://huggingface.co/settings/tokens.
4. Put it in `.env` as `HF_TOKEN=...` (step 5).

If it is missing, loading the pipeline fails with an authorization/gated-repo error.
**The fix is access, not a different diarizer.**

## 5. Environment variables

```bash
cp .env.example .env
```
Fill in `AUDIO_SEARCH_DATABASE_URL` and `HF_TOKEN`. Leave everything else at its default for the
baseline. The first ingest downloads model weights: Whisper `large-v3-turbo` is
~1.6 GB, the pyannote models are small, and MiniLM is ~90 MB. Expect a slow first run.

| Variable | Default | Effect of changing it |
|---|---|---|
| `AUDIO_SEARCH_RRF_K` | `60` | Higher values flatten rank differences; lower values let the top ranks dominate. Change only with a before/after measurement |
| `AUDIO_SEARCH_FUSION_WEIGHT_KEYWORD` | `1.0` | Scales the keyword branch's contribution `w / (k + rank)`. `0.0` disables the branch (diagnostic; logs WARNING). Negative values are rejected |
| `AUDIO_SEARCH_FUSION_WEIGHT_SEMANTIC` | `1.0` | Same, for the semantic branch. **1.0 / 1.0 is the permanent measured baseline** |
| `AUDIO_SEARCH_CANDIDATE_DEPTH_MULTIPLIER` | `5` | Each branch fetches `top_k × multiplier` candidates (50 at top_k 10). Top-K is cut only after fusion. Deeper lists let fusion see more cross-branch agreement at a small latency cost |
| `AUDIO_SEARCH_HNSW_EF_SEARCH` | `40` | Higher improves vector recall at the cost of latency. No reindex needed. Branch depth is guaranteed separately: the repository enables pgvector's iterative HNSW scan (`strict_order`), because a plain scan can silently return fewer rows than requested |
| `AUDIO_SEARCH_SPLIT_SOFT_MIN_SECONDS` / `AUDIO_SEARCH_SPLIT_CAP_SECONDS` | `20` / `45` | Semantic split window for long turns. Chunks must stay under the embedder's **256-token** limit |

The weights are **configuration only**. `/search` accepts no weight parameters.

## 6. Database

```bash
python scripts/init_db.py
```
This creates the database named in `AUDIO_SEARCH_DATABASE_URL` if it is missing, enables
`vector` and applies `db/schema.sql`. It is idempotent, so it is safe to re-run. Expected output:
```
database 'audio_search' created        # or: exists
schema applied; pgvector 0.8.6
```
The schema's own tests confirm the `vector` extension, `vector(384)`, the tsvector
generated column using **`english`** (the same constant the query side uses), the GIN
and HNSW indexes, and HNSW usability:
```bash
python -m pytest tests/integration -q
```

## 7. Verify the install

```bash
python scripts/verify_env.py
```
Expected output (the exact version numbers may differ only if you changed the pins):
```
[ok]   python: 3.12.x
[ok]   ffmpeg: /path/to/ffmpeg
[ok]   audio decode (torchcodec): 442.08s @ 22050 Hz
[ok]   model libraries: faster-whisper 1.2.1, ctranslate2 4.8.2, pyannote.audio 4.0.7
[ok]   embedder: dim=384, max_seq_length=256
[ok]   HF_TOKEN: set

ALL CHECKS PASSED
```
The exit code is 0 on success and 1 if any check fails.

## 7b. Multilingual evaluation audio (optional, dev only)

The translated es/hi/zh evaluation set (`dataset/multilingual/`, Task 17) ships as text. To create its audio:
```bash
brew install espeak-ng            # Linux: sudo apt install espeak-ng  (Spanish/Hindi phonemes)
pip install -r requirements-dev.txt
python scripts/synthesize_multilingual.py      # downloads Kokoro-82M (~330 MB, not gated); writes 18 WAVs
python -m pytest tests/data/test_multilingual_dataset.py -q
```
If you change a translation (`dataset/multilingual/translations/`), run `python scripts/build_multilingual_dataset.py`
and then re-synthesise that language with `--lang <code> --force`.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `database "audio_search" does not exist` | Database not created yet | `python scripts/init_db.py` (step 6) |
| Integration tests fail with `connection failed` | Postgres not running, or a wrong `AUDIO_SEARCH_DATABASE_URL` | `brew services start postgresql@18`, then check the URL. These tests fail rather than skip by design |
| `ffmpeg not on PATH`, or torchcodec fails to load `libavutil` | ffmpeg missing | Install ffmpeg (step 1) and reopen the shell |
| `401`/`403`, "gated repo", "Cannot access" when loading diarization | Conditions not accepted on **both** pyannote repos, or `HF_TOKEN` unset | Step 4 |
| `type "vector" does not exist` | pgvector not enabled in this database | Re-run `python scripts/init_db.py` (step 6). If pgvector isn't installed on the server: `brew install pgvector` / `apt install postgresql-18-pgvector` |
| `expected 384 dimensions, not N` | Embedding model changed without a schema change | Restore `AUDIO_SEARCH_EMBEDDING_MODEL`, or change the schema and re-ingest |
| Keyword search returns nothing for words that are clearly in the transcript | **Text search configuration mismatch**: the tsvector column and the query parser use different configs | Both must be `english`. Check with `SELECT to_tsvector('english','archived') @@ websearch_to_tsquery('english','archiving');` → `t` |
| macOS prints `objc: Class AVF… is implemented in both …` | PyAV (faster-whisper) and Homebrew ffmpeg each bring their own libavdevice | Printed at import. It has not caused a failure so far, but macOS warns it *may*. See `PROGRESS.md` Known Issues. The pipeline decodes each file once and passes the waveform to both models, so the two decoders are never both used on a file |
