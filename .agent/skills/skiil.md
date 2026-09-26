

skiil.md
---
name: audio-hybrid-search
description: "Use this skill for any work on the Audio Hybrid Search project — hybrid keyword + semantic retrieval over two-speaker audio conversations using Whisper transcription, pyannote diarization, semantic chunking, local SentenceTransformer embeddings, weighted RRF fusion, and Postgres + pgvector with tsvector/stemming, evaluated by automated recall@k tests. Trigger whenever the user mentions this project, its files (PLAN.md, PROGRESS.md, HANDOFF.md, AGENT_LOG.md, SOLUTION.md, SETUP.md), or asks to resume, continue, or pick up the build; also trigger for tasks involving the ingestion pipeline (transcribe, diarize, align, chunk, embed, index), semantic or merge-and-split chunking, the hybrid search service, keyword/tsvector/stemming or full-text ranking, RRF or weighted fusion and branch weights, the FastAPI endpoints (/ingest, /search, /search/keyword, /search/semantic, /evaluation), the golden audio dataset, the labeled query set, environment/venv/dependency setup for it, or recall@k / WER / DER / speaker-accuracy / latency evaluation; also trigger for multilingual / non-English / language detection / per-language stemming / multilingual embedding work (compulsory, PLAN.md §7B). Do NOT use for unrelated audio, transcription, or search work outside this project."
---


# Audio Hybrid Search — Build Skill


Hybrid (keyword + semantic) search over **5–6 two-speaker audio
conversations, 8–10 minutes each**. Every hit must return the **containing
file**, the **timestamp**, and the **speaker**. Branches are combined with
**weighted RRF** and sliced to top-K. Graded on automated recall@k against a
labeled query set.


## ⚠️ Compulsory feature: multilingual support (added 2026-09-26)


**The system must ingest and search non-English conversations.** Decided by
the project owner; **core scope, not a stretch goal** (`PLAN.md` §7B,
Task 17). **Implementation checklist with file:line references:
[MULTILINGUAL_UPDATE_PLAN.md](MULTILINGUAL_UPDATE_PLAN.md)**. All decisions are final:


| Stage | Old (English-only) | Now required |
|---|---|---|
| Transcription | `language="en"` forced | Auto-detect (setting `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE`, blank = auto); store language + probability per file |
| Diarization / alignment | — | **Unchanged** (language-independent) |
| Sentence split | `.!?` + space | Also `。！？` (no space), `।` `॥`, `؟` `۔` |
| Embeddings | `all-MiniLM-L6-v2` (English-only, 384) | **`BAAI/bge-m3`**, dense, `vector(1024)`, 8192 tokens, symmetric (no prefixes), CPU or `mps` on a 24 GB Apple Silicon Mac. Measure dim/window at adoption |
| Keyword branch | `english` for every row | **Per-chunk** `search_config` (mapped from language); `search_text` = CJK-bigram(`text`); tsvector = `to_tsvector(search_config, search_text)`; the query goes through the same bigram function and is parsed once per config present. zh/ja/ko → `simple` + bigrams. Unmapped → `simple` + WARNING |
| Results | file, timestamp, speaker | + **language** |
| Languages | English only | **Any** (auto-detected). Evaluated on en + **es, hi, zh** = translations of golden 01–06, re-synthesised (dev-only TTS, e.g. Kokoro-82M) |
| Evaluation | English only | Thresholds gated **per language AND overall**; cross-lingual slice reported; CER primary for `zh` |


**English must not regress** — the English golden set is the before/after
baseline for every multilingual change. **M5 (per-chunk keyword config) must
land before or with Task 5's keyword branch.**


## Start here, every session


Read in this order. **Do not load everything.**


| Step | File | Why |
|---|---|---|
| 1 | [HANDOFF.md](HANDOFF.md) | The resume point — what to do right now, blockers, session procedure |
| 2 | [PROGRESS.md](PROGRESS.md) | Repo state — tasks, environment and endpoint status, measured results, fusion config record, decisions log |
| 3 | [PLAN.md](PLAN.md) | The spec — **only the sections your task needs** (map in `HANDOFF.md` §5) |


Assume **no memory of prior sessions** and possibly a **different model**.
All resumable state lives in these files, never in chat history.


## Your role: principal RAG/search engineer


Work as a principal engineer who has shipped retrieval systems to
production would. A standard of judgment, not a license to build more.
Full standards: `PLAN.md` §0B.


- **Retrieval quality is the product.** Judge every decision by its effect
  on recall, speaker/timestamp correctness, and latency.
- **Measure before you optimize.** Baseline first; one variable at a time;
  never tune on instinct. **For fusion, the baseline is equal weights.**
- **Debug in pipeline order** — transcription → diarization/alignment →
  chunking → embedding → branches → fusion. Quality is lost upstream far
  more often than in the ranker, and most people debug this backwards.
  **Inspect real intermediate artifacts**; don't reason about them.
- **Know which branch should have caught a failed query.** Keyword owns
  exact terms/names/numbers and fails on paraphrase; semantic owns
  paraphrase and fails on rare proper nouns.
- **Design for the swap, not the rewrite.** No infra type leaks upward; the
  pure core stays pure; config is read once at the composition root.
- **Make the system explain itself** — structured logs at stage boundaries,
  **including the active fusion weights per request**.
- **State limits specifically.** "It might not scale" is hand-waving.
- **Taste is knowing what not to build.**


**Deliberately not doing**: re-ranking, query rewriting, multi-vector
retrieval, fine-tuning, caching layers, or a queue. See `PLAN.md` §11.


## Missing packages: install, then record


**If something needed is missing, install it.** Do not stop, do not stub it
out, do not skip the test, do not leave a "not available in this
environment" note. A blocked build helps nobody. Full policy: `PLAN.md` §4B.


**But never silently.** Four steps, same session:
1. **Install into the venv** — never system-wide, never `sudo pip`.
2. **Pin it** with `==` in `requirements.txt` (runtime) or
   `requirements-dev.txt` (tests/lint only).
3. **Record it** in the `PROGRESS.md` decisions log — what, why, which file.
4. **Update `SETUP.md`** if a fresh clone now needs a new step.


**System tools** (`ffmpeg`, Postgres client) aren't pip packages —
install via the platform package manager and **add them to `SETUP.md`
prerequisites** with commands for macOS and Linux. `ffmpeg` is the most
common first-run failure; list it even though pip never sees it.


**Model weights** download on first use — expect a slow first run and say
so. **pyannote is gated**: if it fails to load, the fix is accepting the
model conditions and supplying an HF token, **not** swapping in a different
diarizer. Never silently substitute a model to get past an access error.


**Still needs justification first**: anything that changes the approved
stack (§4) — a second vector store, a search engine, an ORM, a task queue.
That's a design decision, not an install. Record the reasoning in
`PROGRESS.md` *before* adding it, and prefer stdlib and the locked stack.


Before installing: confirm the venv is active, and check it isn't already
present under a different import name.


## API surface — five endpoints


Full spec: `PLAN.md` §7A. The API is the composition root and holds **no
retrieval logic** — every endpoint delegates to a service.


| Endpoint | Method | Purpose |
|---|---|---|
| `/ingest` | POST | Accepts a **list of files**; per-file outcomes; **one failure must not abort the batch**; idempotent per checksum |
| `/search` | GET | **The graded path.** Both branches → weighted RRF → top-K. **No weight parameters** |
| `/search/keyword` | GET | Keyword branch alone — **diagnostic only** |
| `/search/semantic` | GET | Semantic branch alone — **diagnostic only** |
| `/evaluation` | GET/POST | Runs the labeled query set via the service method; returns all metrics **plus the active weights and k**. Reports only, never writes |


**Three binding rules for the branch endpoints**: they reuse the **exact
same repository methods** as `/search` (a drifting reimplementation makes
diagnosis worse than useless); they are **never** what evaluation calls for
primary metrics; and they must not pull fusion into the API layer. Mark both
as diagnostic in their route descriptions.


## Keyword branch: stemming, parsing, ranking


Full spec: `PLAN.md` §7.


> **Multilingual:** the configuration is **per chunk** (`chunk.search_config`,
> `english` for English rows), over `search_text` (CJK bigrams). Everything
> below still applies, **per row**.


**Stemming is handled by Postgres, not application code.** Use the
**`english`** text search configuration **identically on both sides** —
generating the stored `tsvector` column *and* parsing the query.


> **A configuration mismatch is the quietest failure in this branch.**
> Indexed and query lexemes get produced by different rules, matches vanish,
> and nothing errors. Verify both sides explicitly.


- Snowball stemming + stop-word removal, so *archiving / archived /
  archives* reduce to a common lexeme — inflection tolerance with no custom
  logic.
- Stemming happens at index time via the **generated column** — consistent
  across every chunk by construction, cannot drift. **Never stem in
  application code.**
- **Word positions are retained** — the ranking function depends on them.


**Parsing**: web-search-style, so quoted phrases, `OR`, and `-exclusions`
behave as users expect and malformed input degrades gracefully.


**Ranking**: cover-density (rewards query terms close together and in
natural order, using the stored positions), with **length normalization**
and **score saturation**. Approximates BM25-style behaviour without full
BM25 — note the difference in `SOLUTION.md`.


Results come back ordered best-first; **the 1-based row position is what
fusion consumes**, not the raw score.


**Known limitation**: stemming cuts both ways — better recall on inflected
forms, but it can conflate distinct technical terms sharing a stem. **Check
for a stemming collision before blaming the fusion weights.**


## Fusion: weighted RRF with configurable weights


Full spec: `PLAN.md` §7.


**The scoring rule.** Each chunk's fused score is the **sum, over each
branch it appears in, of that branch's weight divided by (k + its 1-based
rank within that branch)**. Sort descending, slice to top-K.


**Three properties that must hold — test each:**
1. **Rank is 1-based and scoped to its own branch.** A chunk ranked 3rd in
   keyword and 7th in semantic contributes two separate terms.
2. **The weight multiplies the per-branch contribution, not the final
   score.** Weighting after summing scales every branch identically and
   changes nothing — a silent no-op bug.
3. **Absence contributes nothing.** No penalty, no zero-fill.


**Why weighting is meaningful here**: rank position is scale-free, so a
weight expresses "how much do I trust this branch's ordering" rather than an
artefact of score magnitude.


**Configuration rules:**


| Concern | Rule |
|---|---|
| Defaults | **1.0 / 1.0** — equal weighting, the permanent measured baseline |
| Where they live | Env-backed settings, read **once at the composition root** |
| How they reach fusion | Injected into the search service, passed per call to the pure fusion function. Fusion holds no state |
| Validation | Negative/non-numeric → typed error. **0.0 is legal** (disables a branch — useful diagnostic) but logs WARNING |
| Unknown branch name | Configuration error — fail loudly |
| Missing from the map | Defaults to 1.0 |
| Per-request override | **Not in scope.** No query parameter |
| Observability | Log active weights on every search request |


**Candidate depth**: each branch retrieves **more than K** (named constant).
**Slice to top-K only after fusion** — slicing branches first discards
exactly the cross-branch agreements fusion exists to find.


**Tuning discipline**: equal weights are the permanent baseline — measure it
first. Diagnose with per-branch recall before touching a weight. One change,
re-measure, record both numbers. **A change must improve both precision and
recall** — trading one for the other, or helping one query type at the
other's expense, is not an improvement and gets reverted. **Beware
overfitting** — ~90 queries is small. Disclose any non-default weights in
`SOLUTION.md`.


## Chunking: semantic boundaries for long turns


Full spec: `PLAN.md` §6.


**Why it exists.** Long conversational turns drift across two or three
topics. Cutting one at a fixed 45s mark lands mid-topic nearly every time,
producing two chunks that each hold half of two ideas — neither embeds
cleanly, so neither ranks. **This is the most common cause of "the text is
in there but search can't find it."**


**Three steps:** merge same-speaker runs (~15s target, ~30s cap, never
across a speaker boundary) → split long turns at *meaning* boundaries →
link prev/next.


**The semantic split**: sentence-split the turn, embed sentences in **one
batched call per turn**, compare consecutive sentences, and past a ~20s soft
minimum treat every sentence boundary as a split candidate. At the ~45s cap,
split at the **lowest-similarity candidate** — the biggest topic change —
not at the cap itself.


**Four safeguards, all non-negotiable:**
1. **Deterministic fallback** on any embedder failure — a smarter split must
   never fail an ingest. Log at WARNING; report the fallback count.
2. **Injected `Embedder` port only**, never a concrete model.
3. **Determinism preserved** — ingest-time only.
4. **Both chunkers must agree** below the split cap. Assert it in a test.


**Build the deterministic chunker first**, get the pipeline working, then
layer the semantic splitter on top.


## Care over speed — how to implement


**Speed is not a success criterion; correctness is.** Full rules:
`PLAN.md` §0.


Read before you write · think the logic through first · enumerate edge
cases before coding · test alongside the logic · **verify, don't assume**
("it should work" is not a verification) · one concern at a time · **stop
and find the cause** of anything unexpected, never paper over it · **never
tune a threshold to pass** · Done = code exists **and** tests pass **and**
it ran against real data **and** it's committed.


### The four high-risk areas — go slowly here


| Area | Why it's dangerous |
|---|---|
| **Alignment** (§6.4) | Off-by-one and overlap-tie errors silently corrupt every speaker label; invisible until evaluation |
| **Chunking** (§6) | Boundary and time-apportionment bugs misplace timestamps — a direct violation of the core requirement |
| **Fusion** (§7) | Ranks must be 1-based and per-branch, and weights must multiply the *per-branch* term. Errors still look plausible while degrading recall |
| **Evaluation** (§10) | A bug that *inflates* a metric never announces itself. Verify against a hand-computed example |


## Code style: short, optimized where it counts, minimal ceremony


Full detail: `PLAN.md` §0B.10–12.


**Write it short if short is still obvious.** Comprehensions over
list-building loops, `dict.get` with a default over try/except, guard
clauses over nested conditionals, stdlib helpers over hand-rolled ones. If
brevity would obscure the logic, keep the longer form and move on. **Concise
≠ clever**: nested comprehensions, compression-walrus, and one-liners
needing a comment are *longer* to read.


**Stay explicit in the high-risk areas** — alignment overlap comparison,
chunk boundary arithmetic, similarity comparison in the splitter, and
**weighted rank accumulation in fusion**.


**Optimize search, not ingestion** (the p95 target applies to search only):


| Do by default | Don't without a measurement |
|---|---|
| Batch embedding calls — one per batch, one per *turn* in the splitter | Caching layers |
| Hydrate only the top-K fused ids | Parallelism beyond the two branches |
| Rank/order/limit in SQL where the indexes are | Micro-optimizing pure functions |
| Order by the raw distance operator (an alias disables the vector index) | Connection-pool tuning |
| Deduplicate file lookups — one query, not N | Swapping data structures for speed |
| Load models once at the composition root | |


**Minimal ceremony — skip:** docstrings on self-evident functions, comments
restating code, type hints on obvious locals and trivial helpers, section
banners, `Args:`/`Returns:` blocks on private functions.


**Keep — load-bearing, not ceremony:**
- **Type hints on domain ports and public service methods** — the contract
  between layers
- **Type hints on FastAPI routes and Pydantic models** — Swagger/OpenAPI is
  generated from them; dropping these silently removes a required
  deliverable. Not negotiable
- **A brief docstring on each high-risk function** (alignment, merge,
  deterministic split, semantic split, weighted fusion)
- **Comments explaining *why*, never *what*** — including why the text
  search configuration must match on both sides


Rule of thumb: **if removing it would let someone misuse or accidentally
break the code, keep it. Otherwise delete it.**


## Environment: always venv, always pinned, always documented


**Before writing any code, in every session.** Never install into the system
interpreter. Never run a script outside the venv. Detail: `PLAN.md` §4A/§4B.


| Artifact | Rule |
|---|---|
| `.venv/` | Create at repo root on the first session; **activate every session thereafter**. Gitignored — never committed |
| `requirements.txt` | Every runtime dependency, **pinned** (`==`). Add it the moment you import it |
| `requirements-dev.txt` | Test/lint deps (pytest, pytest-asyncio, WER/DER scoring), separate from runtime |
| `SETUP.md` | **A grader must reach a working system from a fresh clone using only this file** |
| `.env.example` | Every required variable with placeholders, **including fusion weights and RRF k**. Commit this; **never commit `.env`** |
| `.gitignore` | At minimum `.venv/`, `.env`, `__pycache__/`, model caches |


### `SETUP.md` must cover, in order
1. **Prerequisites** — Python version, **`ffmpeg`** (Whisper needs it)
2. **Venv** — create and activate, macOS/Linux and Windows
3. **Install** — `requirements.txt`, then `requirements-dev.txt`
4. **Hugging Face gated access** — accept conditions on **both**
   `pyannote/speaker-diarization-3.1` *and* `pyannote/segmentation-3.0`,
   create a token, set it via env. **The single most likely reason a fresh
   clone fails** — make it prominent, not a footnote
5. **Environment variables** — copy `.env.example` to `.env`, fill DB URL and
   HF token; **document the fusion weight and RRF k variables**
6. **Database**  apply `db/schema.sql`, confirm the
   `vector` extension is enabled **and the tsvector column uses `english`**
7. **Verify** — one command proving the install works, with the **expected
   output stated**
8. **Troubleshooting** — missing `ffmpeg`, HF/gated rejection, pgvector not
   enabled, embedding dimension mismatch, **text search config mismatch**


## Tracking files: bootstrap or reuse


- **File exists → use it.** Read and update in place. **Never overwrite or
  recreate** — that destroys project history and is a defect.
- **File missing → create it** using `PLAN.md` §15.1, populated with the
  repo's *actual* state, before any implementation work.
- **Repo wins any disagreement** with a tracking file.


## Locked stack — settled, do not relitigate


| Concern | Choice | Constraint it imposes |
|---|---|---|
| Transcription | Whisper `large-v3-turbo`, faster-whisper, local | Needs `ffmpeg`. Fallback `small` if hardware struggles. **Language auto-detected (§7B M1)** |
| Diarization | `pyannote/speaker-diarization-3.1` | **Gated**: accept conditions on `speaker-diarization-3.1` *and* `segmentation-3.0`, supply HF token. Mono 16 kHz. `num_speakers=2` |
| Embeddings | **`BAAI/bge-m3`** (was `all-MiniLM-L6-v2`, English-only) | **1024 dims** → `vector(1024)`; 8192-token window (measure at adoption). Symmetric. Also drives the semantic splitter |
| Keyword search | Postgres FTS, **per-chunk config** (`english` for English, `simple` + CJK bigrams for zh/ja/ko), generated GIN-indexed tsvector | Same config **and same bigram function** at index and query time, **per row**. Never stem in application code |
| Vector index | **HNSW** on the embedding column | No training step, so it works on an empty table. `m`/`ef_construction` recorded in the schema; `ef_search` configurable |
| Metrics | `jiwer` (WER + CER) · `pyannote.metrics` (DER) | **Dev dependencies only** — never imported by the served system |
| Chunking | Merge + semantic split + link | Deterministic fallback mandatory |
| Fusion | **Weighted RRF**, k=60, weights from config | Defaults 1.0 / 1.0; config only, never a query parameter |
| Storage | Postgres + pgvector | Single instance — no Redis, no Elasticsearch, no separate vector store |
| API / tests | FastAPI · pytest + pytest-asyncio | Five endpoints (§7A) |
| Dataset | User-provided synthetic two-speaker audio | Copyright-safe; reference transcripts give exact ground truth for WER, DER, speaker accuracy |


Full rationale: `PLAN.md` §17.


## Success criteria


**Primary — fixed, never adjusted**: recall@5 ≥ 0.80 · recall@10 ≥ 0.90
(both **split by keyword vs semantic**) · speaker accuracy ≥ 0.90 · latency
p95 < 500 ms (target).


**Secondary — measured and reported, no threshold**: WER + **CER**
(`jiwer`) · DER (`pyannote.metrics`) · indexing throughput per stage · MRR ·
**per-branch recall** (the evidence base for any weight decision).


**Five env-backed settings**, all shipping at defaults, all changed only
with a measurement: RRF `k` · branch weights · HNSW `ef_search` ·
per-branch candidate depth multiplier · semantic-split soft minimum and cap.


Read them together: high WER explains poor recall; **a low CER beside a high
WER means the gap is tokenization, not mishearing**; high DER explains poor
speaker accuracy; **good DER with poor speaker accuracy points at the
alignment step, not the diarizer.**


**If a primary target is missed, fixing that miss is the work** — not a
stretch goal, not a threshold change, not reflexive weight-fiddling.


## Non-negotiables


- **Multilingual support is compulsory** (`PLAN.md` §3 item 6, §7B, Task 17)
  — core scope, not gated by §11. English must not regress.
- **Build only what `PLAN.md` §3 scopes.** §11 items are gated: all core
  tasks Done, all primary criteria met, time remaining, **and explicit user
  approval** — one at a time.
- **Never assume a default.** Ambiguity goes to `PROGRESS.md` Open
  Questions, surfaced — not guessed.
- **Missing packages get installed, pinned, and recorded** — never stubbed,
  skipped, or worked around (§4B).
- **`GET /search` is the only graded endpoint**, and it stays deterministic:
  one complete result set per query, no streaming, no generative model, no
  randomness, no per-request weight overrides.
- **Embeddings generate and index locally** — hard constraint from the brief.
- **Layers point inward**: `api → application → domain`, `infra` implements
  ports. Application code never imports infra and contains no SQL. **The API
  layer holds no retrieval logic.**
- **End every session** by updating `PROGRESS.md`, pinning any new
  dependency, appending to `AGENT_LOG.md`, refreshing the `HANDOFF.md`
  resume point, and committing.


## Five known traps


1. **Text search configuration mismatch.** If the tsvector column and the
   query parser use different configurations, stemmed lexemes won't line up
   and matches disappear **with no error**.
2. **Diarizer speaker ids are arbitrary per file.** Align predicted to
   reference labels before scoring speaker accuracy, or a correct
   diarization scores near zero.
3. **The 256-token embedder limit** (measured `max_seq_length`; 512 was wrong) must stay above the chunk size caps.
4. **Slicing branches to K before fusion** silently discards the
   cross-branch agreements fusion exists to find.
5. **English-only leftovers (§7B).** An English-only embedder or a forced
   `english`/`en` anywhere makes non-English content silently unfindable —
   nothing errors. Unmapped languages must fall back to `simple` **with a
   WARNING**, never to `english`. An asymmetric embedder with a missing or
   swapped `query:`/`passage:` prefix loses recall silently (bge-m3 is
   symmetric, so this only matters if the e5 latency fallback is used). The
   CJK bigram function must be identical on the index and the query side.

