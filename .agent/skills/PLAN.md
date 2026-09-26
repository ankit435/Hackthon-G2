# Audio Hybrid Search — Build Plan (Agent Execution Spec)


> **Read this first.** This document is the single source of truth for what to build.
> It contains **no code**. Do not copy snippets from anywhere into implementation
> without deriving them from the requirements below.
>
> **⚠️ Amended 2026-09-26: multilingual support is COMPULSORY** (project owner decision).
> The system must ingest and search conversations in languages other than English.
> Spec: **§7B**. Task: **17**. Where an older line in this document says "English only",
> `english` config, `language="en"` or `all-MiniLM-L6-v2`, **§7B overrides it**.


---


## 0. Rules for the Implementing Agent


These are binding. Violating them is a defect, even if the code works.


### Scope discipline


1. **Build only what Section 3 (Scope) lists.** Anything in Section 11
   (Deferred Stretch Goals) must not be implemented, scaffolded, stubbed, or
   configured for **until the Section 11 gate is satisfied** — all core tasks
   done, all success criteria met, time remaining, **and the user has
   explicitly approved that specific item**.
2. **Do not assume. Ask or fail loudly.** If a requirement is ambiguous
   (model choice, threshold, file path, dataset source), stop and surface
   the question in `PROGRESS.md` under "Open Questions" rather than
   inventing a default and moving on.
3. **No silent defaults at system boundaries.** Validate inputs where they
   enter the system; raise typed domain errors with context (stage, file
   id, query hash). Never swallow an exception.
4. **Always work inside the project venv** (Section 4A). No system-wide
   installs.
5. **If something needed is missing, install it — then pin and document it
   immediately** (Section 4B). Never work around a missing package with a
   stub, a mock, a skipped test, or a "not available in this environment"
   note. But an install is never silent: pinned in `requirements.txt` and
   recorded in `PROGRESS.md` in the same session.
6. **Every deliverable in Section 12 must exist** before the work is
   considered complete. A working search path with no evaluation tests is
   an incomplete submission.
7. **Log every agent session** in `AGENT_LOG.md` using the template in
   Section 16 — a graded submission requirement, not optional housekeeping.
8. **Deterministic evaluated path.** The function behind `GET /search` —
   the one the recall@k tests call — must return one complete result set
   per query. No streaming, no generative model, no randomness, and no
   per-request weight overrides.


### Care over speed — how to implement, not just what


**Speed is not a success criterion; correctness is.** Nobody is measuring
how fast this was written — only whether the numbers in Section 2 hold and
whether the next person can trust the code.


9. **Read before you write.** Before modifying or extending existing code,
   read the surrounding module and its tests.
10. **Think the logic through before implementing it, especially in the
    high-risk areas.** Four places carry disproportionate correctness risk:
    - **Alignment** (§6.4) — off-by-one and overlap-tie errors silently
      corrupt every downstream speaker label; invisible until evaluation.
    - **Chunking** (§6) — merge, semantic split, time apportionment,
      prev/next linkage. Bugs misplace timestamps, a direct violation of
      the core requirement.
    - **Fusion** (§7) — rank indexing must be 1-based and per-branch, and
      weights must multiply the per-branch contribution, not the final
      score. Errors still produce plausible rankings while degrading recall.
    - **Evaluation** (§10) — a bug that inflates a metric is worse than one
      that breaks the build, because it will not announce itself.


    For each: state the intended behaviour, enumerate the edge cases, decide
    what happens in each, and only then write it.
11. **Enumerate edge cases explicitly before coding a function.** At minimum:
    empty input, single-element input, zero-duration segment or turn,
    whitespace-only chunk text, a query matching nothing in one branch, a
    branch weight of zero, a file failing mid-pipeline, ties in ranking or
    overlap.
12. **Write the test alongside the logic, not after the fact.** Pure
    functions (chunking, fusion, alignment) are testable with plain data and
    no infrastructure.
13. **Verify, don't assume, at every boundary you cross.** Run it and inspect
    real output before declaring a stage complete: embedding dimension
    matches the schema, timestamps land where the audio says they do, the
    tsvector column is populated with the expected configuration, the
    indexes are used. **"It should work" is not a verification.**
14. **One concern at a time.** Finish, test, and commit a coherent unit
    before starting the next.
15. **When something is unexpected, stop and find the cause.** Do not paper
    over a surprising result with a retry, a broadened exception handler, a
    default value, or a loosened assertion. Record what you found.
16. **Never tune a threshold to make a test pass.** If recall misses,
    diagnose the retrieval failure (§10.5). Thresholds in Section 2 are
    fixed. **A documented miss with an honest root cause is a good
    submission; a passing number obtained by moving the goalposts is a
    failed one.** (Fusion weights are *configuration*, not a threshold — but
    they carry their own overfitting discipline; see §7.)
17. **Leave the reasoning behind non-obvious code in the code** — *why*, not
    *what*.
18. **A task is Done only when: the code exists, its tests pass, it has been
    run against real data, and it is committed.**


---


## 0B. Engineering Standard — Work as a Principal RAG/Search Engineer


Section 0 says what to build and how carefully. This section says **to what
standard**. Adopt the judgment of a principal engineer who has shipped
retrieval systems to production.


**Important**: a standard of *judgment*, not a mandate to build more.
Principal-level work at this scale is mostly **subtraction**.


### 1. Retrieval quality is the product
Every decision is judged by its effect on recall, speaker/timestamp
correctness, and latency. If a change cannot be tied to a Section 2 number,
it is not an improvement — it is scope.


### 2. Measure before you optimize
- Establish the baseline first: ingest, run the full labeled query set,
  record every Section 2 metric. **For fusion the baseline is equal weights
  (1.0 / 1.0).**
- When a metric misses, **diagnose before changing anything** (§10.5).
- Change one variable at a time and re-measure.


### 3. Debug in pipeline order — quality is usually lost upstream
1. **Transcription** — is the text correct? (WER, §2.)
2. **Diarization & alignment** — labels and boundaries right? (DER, §2.)
3. **Chunking** — is the answer split across two chunks? Is a chunk so long
   the signal is diluted?
4. **Embedding** — is the query far from how the answer was phrased? Is a
   chunk exceeding the token window and being truncated?
5. **Retrieval branches** — is one branch returning nothing for this query
   shape? (Use `/search/keyword` and `/search/semantic` — §7A.)
6. **Fusion** — only now consider ranking and weights.


Most teams debug this backwards and waste the day. **Inspect the
intermediate artifacts** rather than reasoning about them abstractly.


### 4. Understand the two branches' complementary failure modes
- **Keyword** is precise on exact terms, names, jargon, numbers — and fails
  on paraphrase, synonyms, conceptual queries.
- **Semantic** handles paraphrase and intent — and is unreliable on rare
  proper nouns, identifiers, exact-phrase requirements.


When a query fails, identify **which branch should have caught it**. That
question usually names the root cause, and tells you whether a weight change
would help or just trade one failure for another.


### 5. Design for the swap, not the rewrite
- No infra type (model object, DB row, library exception) leaks into
  application or domain code.
- Keep the pure core pure. (The semantic splitter in §6 is the one place
  needing an embedder — it takes the **injected port**, never a model.)
- Config is read once at the composition root. **Fusion weights follow this
  exactly** (§7).
- **The API layer holds no retrieval logic** (§7A).


### 6. Make the system explain itself
Structured logs at every stage boundary — durations, counts, per-branch
result sizes, **the active fusion weights** — turn "recall dropped" from a
guess into an answerable question.


### 7. Idempotency and failure isolation are not optional
Checksum-based skip, single transaction per file, no partial writes. **A
batch ingest isolates failures per file** (§7A).


### 8. Write code the next engineer can own
Small named functions; pure core with I/O at the edges; honest names; typed
errors carrying context; no cleverness needing a paragraph to justify.


### 9. Know the difference between a real limit and an unexamined one
State limitations **specifically**. "It might not scale" is hand-waving.
"Chunks at the 45s cap dilute the embedding signal, so single-fact queries
against long monologues rank lower — word-level timestamps would allow
tighter chunks" is engineering. `SOLUTION.md` should read like the second.


### 10. Write concise code — but never at the cost of clarity
**Default to the shortest version that is still obvious.** If brevity would
obscure the logic, keep the longer form and move on.


**Prefer short where it reads better:** a comprehension over a loop that
only builds a list; `dict.get(key, default)` over a four-line try/except;
one well-named expression over a single-use temporary; early returns over
nested conditionals; stdlib helpers over hand-rolled equivalents.


**Keep it long where short would hide the logic** — alignment overlap
comparison, chunk boundary arithmetic, similarity comparison in the
splitter, and **weighted rank accumulation in fusion**. Never chain so much
that an intermediate value can't be inspected in a debugger or log line.


**Concise is not clever.** Nested comprehensions, compression-walrus,
single-letter names, and one-liners needing a comment are all *longer* to
read. Reject them.


### 11. Optimize where it matters — and only there
The p95 target applies to **search**, not ingestion.


**Do by default:** batch embedding calls (one per batch; the splitter
batches per long turn) · hydrate only the top-K fused ids · rank/order/limit
in SQL where the indexes live · order by the raw distance operator (an alias
silently disables the vector index) · deduplicate file lookups · load models
once at the composition root.


**Not without a measurement** (§0B.2): caching layers, parallelism beyond
the two branches, micro-optimizing pure functions, connection-pool tuning,
swapping data structures for speed.


### 12. Minimal ceremony — but keep what carries meaning


**Skip:** docstrings on short self-evident functions; comments restating the
code; type hints on obvious locals and trivial helpers; section banners,
`Args:`/`Returns:` blocks on private functions, author tags.


**Keep — load-bearing, not ceremony:**
- **Type hints on domain ports and public service methods** — the contract
  between layers.
- **Type hints on FastAPI routes and Pydantic models.** OpenAPI/Swagger is
  generated from them; dropping these silently removes a required
  deliverable (§12). Not negotiable.
- **A brief docstring on each high-risk function** (alignment, merge,
  deterministic split, semantic split, weighted fusion) stating the contract
  and edge-case decisions.
- **Comments explaining *why*, never *what*** — why the text search
  configuration must match on both sides, why time is apportioned by
  character length, why the default weights are what they are.


Rule of thumb: **if removing it would let someone misuse or accidentally
break the code, keep it. Otherwise delete it.**


### 13. Taste is knowing what not to build
At this scale, deliberately **not**: re-ranking, query rewriting,
multi-vector retrieval, fine-tuning, caching layers, job queues. The
reasoning belongs in `SOLUTION.md` — **documented restraint is a stronger
signal than unnecessary machinery** (§11).


---


## 1. Problem Statement (restated, authoritative)


Build hybrid (keyword + semantic) search across **5–6 two-speaker audio
conversations, 8–10 minutes each**. A search must return, for every hit:


- the **containing file**
- the **timestamp** (start/end within that file)
- the **speaker** who uttered it


Users must be able to find both **exact words spoken** and **semantically
similar phrasing**. Evaluate with **automated recall@k tests** against a
small labeled query set.


### Hard constraints from the brief
| Constraint | Requirement |
|---|---|
| Language | Python or TypeScript |
| Storage | RDBMS with embedding support (Postgres + pgvector) |
| Embeddings | Generated **and indexed locally** — no hosted embedding API |
| Transcription | Local **or** hosted — either is acceptable |
| Coding agent | Permitted, but usage **must be disclosed** with how it was prompted |
| Delivery | Git repo containing code + golden dataset + tests, plus a Markdown/PDF design doc |
| **Spoken language** (added 2026-09-26, project owner) | **Multilingual — compulsory.** Ingest and search non-English conversations; a query in one language may retrieve a chunk in another. Spec in §7B |


---


## 2. Success Criteria


### Primary — pass/fail


| Metric | Target |
|---|---|
| recall@5 | ≥ 0.80 |
| recall@10 | ≥ 0.90 |
| recall@5 / recall@10, reported separately for keyword vs semantic queries | Same targets, reported split |
| Speaker attribution accuracy on top-k results | ≥ 0.90 |
| Search latency p95 (warmed-up, excludes model cold start) | < 500 ms (target) |


### Secondary — measured and reported, no pass/fail threshold


These make the system **diagnosable**, not gated. They tell you *where*
quality was lost when a primary metric misses (§0B.3).


| Metric | Why it is tracked |
|---|---|
| **WER** and **CER** (transcription) | The ceiling on everything downstream. When WER looks bad but CER is fine, the gap is tokenization rather than genuine mishearing — that changes where you look next |
| **DER** (diarization) | Explains speaker-attribution misses; separates a *diarization* failure from an *alignment* failure |
| **Indexing throughput** (audio-minutes per wall-clock minute, per stage) | Production-readiness signal, from existing `ingest.*` log events (§9) |
| **MRR** | Catches relevant results at rank 9–10 that recall@10 still passes |
| **Per-branch recall** (keyword-only, semantic-only, pre-fusion) | The evidence base for any fusion weight change (§7) |
| **Per-language results** (§7B M8): recall@k, speaker accuracy, WER/CER per language + a cross-lingual slice | Shows whether multilingual support works, and that English did not regress. Whether primary thresholds apply per language is Q24 |


Report WER and DER against the dataset's reference transcripts and speaker
turns (§17 Q1) — no extra labelling cost. **Both will look flattering on
clean synthetic audio; say so in `SOLUTION.md`.**


**Primary thresholds are fixed** (Rule 16). Secondary metrics have no
thresholds precisely so there is nothing to game.


---


## 3. Scope — What To Build


1. **Ingestion pipeline** — audio files in, indexed searchable chunks out.
2. **Hybrid search** — keyword + semantic branches combined by **weighted
   RRF** with configurable per-branch weights, returning ranked top-K.
3. **API** — the five endpoints in §7A.
4. **Golden dataset + labeled query set.**
5. **Automated evaluation suite** — recall@k, speaker accuracy, latency,
   WER/DER, indexing throughput, chunking sanity checks.
6. **Multilingual support — compulsory (§7B, Task 17).** Language detected
   per file, stored per chunk, language-correct keyword stemming, a
   multilingual embedding model, script-aware sentence splitting, and
   evaluation reported per language. **This is core scope, not a §11 stretch
   goal** — the §11 gate does not apply to it.


---


## 4. Approved Stack


| Concern | Choice | Note |
|---|---|---|
| Language | Python | |
| API | FastAPI | OpenAPI/Swagger with no extra dependency |
| Database | Postgres + pgvector | Single instance. No Redis, no Elasticsearch, no separate vector DB |
| Keyword search | Postgres FTS, **per-chunk text search configuration** (`english` for English) | Generated, GIN-indexed tsvector column (§7). **Amended by §7B**: the config follows each chunk's language |
| Transcription | Whisper `large-v3-turbo` via faster-whisper, local | See §17. **Amended by §7B**: language auto-detected, not forced to `en` |
| Diarization | `pyannote/speaker-diarization-3.1` | Gated model — §17 and `SETUP.md`. Language-independent; unchanged by §7B |
| Embeddings | **A multilingual model** (was `all-MiniLM-L6-v2`, English-only), local | Mandatory: local generation and indexing. Also drives the semantic splitter (§6). **Amended by §7B**; final model is Q22 |
| Tests | pytest + pytest-asyncio | |
| Metrics | `jiwer` (WER/CER), `pyannote.metrics` (DER) | **Dev dependencies only** — the served system never imports them (Q15) |
| Vector index | **HNSW** on the embedding column | Configurable `m` / `ef_construction` / `ef_search` (Q10) | Postgres/pgvector 


Anything beyond this list follows §4B.


---


## 4A. Environment, Dependencies & Setup Documentation


**Mandatory from the first session.** A reproducible environment is part of
the deliverable. A grader who cannot start the project cannot grade it.


### Required artifacts


| Artifact | Rule |
|---|---|
| `.venv/` | Virtual environment at repo root. Create on the first session; **activate at the start of every session thereafter**. Gitignored — **never committed** |
| `requirements.txt` | Every **runtime** dependency, version-pinned with `==`. Added in the same session it is first imported |
| `requirements-dev.txt` | Test and lint dependencies only (pytest, pytest-asyncio, WER/DER scoring, formatters) |
| `SETUP.md` | Clean-machine setup. **A grader must reach a working system from a fresh clone using only this file** |
| `.env.example` | Every required environment variable with placeholders, **including the fusion weights and RRF k** (§7). Committed. **`.env` itself is never committed** |
| `.gitignore` | At minimum: `.venv/`, `.env`, `__pycache__/`, model caches, large local artifacts |


### `SETUP.md` must cover, in this order


1. **Prerequisites** — Python version, and **`ffmpeg`** (Whisper
   requires it; its absence is a common first failure).
2. **Virtual environment** — create and activate, macOS/Linux and Windows.
3. **Install dependencies** — `requirements.txt`, then `requirements-dev.txt`.
4. **Hugging Face gated model access** — accept conditions on **both**
   `pyannote/speaker-diarization-3.1` **and** `pyannote/segmentation-3.0`,
   create an access token, set it via env. **The single most likely reason a
   fresh clone fails** — make it prominent, not a footnote.
5. **Environment variables** — copy `.env.example` to `.env`, fill in the DB
   URL and HF token. **Document the fusion weight and RRF k variables with
   their defaults and what changing them does.** Note the first run
   downloads multi-GB model weights.
6. **Database** —  `db/schema.sql`, confirm the
   `vector` extension is enabled, the embedding dimension matches the model
   (384), and **the tsvector generated column uses the `english`
   configuration**.
7. **Verify the install** — one command proving the system works, with the
   **expected output stated**.
8. **Troubleshooting** — missing `ffmpeg`, HF/gated-model rejection,
   pgvector not enabled, embedding dimension mismatch, **text search
   configuration mismatch between index and query**.


---


## 4B. Missing Packages and Tools — Install, Then Record


**If something needed to do the work is missing, install it.** Do not stop,
do not stub it out, do not skip the test, do not leave a "not available in
this environment" comment. A blocked build helps nobody.


**But an install is never silent.** Every one follows the same four steps,
**in the same session**:


1. **Install into the project venv** — never system-wide, never `sudo pip`.
2. **Pin it** with `==` in `requirements.txt` (runtime) or
   `requirements-dev.txt` (tests/lint/formatting only). An unpinned
   dependency is a broken build for whoever comes next.
3. **Record it** in the `PROGRESS.md` decisions log: what, why, which file
   it went in. One line is enough.
4. **Update `SETUP.md`** if it changes what a fresh clone must do.


### System-level tools (not pip)
`ffmpeg`, and the Postgres client are OS packages, not Python ones.
If one is missing, install it through the platform's package manager and
**add it to the `SETUP.md` prerequisites** with the install command for at
least macOS and Linux. `ffmpeg` in particular is the most common first-run
failure — it must be listed as a prerequisite even though pip never sees it.


### Model weights and gated access
Whisper and SentenceTransformer weights download on first use — expect a
slow first run and say so in `SETUP.md`. **pyannote is gated**: if it fails
to load, the fix is accepting the model conditions and supplying an HF
token, **not** swapping in a different diarizer. Never silently substitute a
model to get past an access error; that is a decision, and it goes in the
decisions log.


### What still requires justification
Installing is the default for anything the plan already implies. But
**adding a dependency that changes the approved stack (§4) — a second
vector store, a search engine, an ORM, a task queue — is a design decision,
not an install.** Record the justification in `PROGRESS.md` *before*
adding it, and prefer the standard library and the locked stack first
(Rule 5, §0B.13).


### Sanity check before installing
Confirm the venv is active, and check the package isn't already present
under a different import name. Two packages solving the same problem is
worse than one.


---


## 5. Architecture


Four layers. Dependencies point inward only.


```
api → application → domain ← infra (implements domain ports)
```


### domain
Interfaces (ports) and models only. No implementation, no I/O, no
third-party SDK imports.
- Ports: `Transcriber`, `Diarizer`, `Embedder`, `ChunkRepository`,
  `AudioFileRepository`
- Models: chunk, audio file, ranked result, search result item
- Typed exceptions so infra exceptions never leak upward


### infra
One adapter per port: Whisper, pyannote, SentenceTransformer, Postgres
repositories. **All SQL lives here and nowhere else.**


### application
Services constructed with domain ports only — never importing infra:
- **Ingest pipeline** (§6) · **Search service** (§7) · **Evaluation
  service** (§10), called by `/evaluation` and by the pytest suite


Also holds the chunking and fusion strategies. Fusion is fully pure;
chunking is pure except the semantic splitter, which receives the
`Embedder` **port** by injection (§6).


### api
The **composition root** — the only module importing both `infra` and
`application`. Wires adapters via dependency injection, maps domain
exceptions to HTTP status codes, and reads configuration from a single env-backed settings object. **Five things are
configurable and live here**: the RRF `k`, the branch weights (§7), the
HNSW `ef_search`, the per-branch candidate depth multiplier, and the
semantic-split soft minimum and cap (§6). Services never read environment
variables directly. **The API layer contains no retrieval logic** (§7A).


### Patterns this enforces (state these in the design doc)
- **Ports & adapters** — swapping Whisper or pgvector means one new infra
  file plus one wiring line
- **Repository** — application code never writes raw SQL
- **Strategy** — chunking and fusion are swappable units
- **Dependency injection** — every service is constructible with fakes, so
  tests need no database or model downloads


---


## 6. Ingestion Pipeline


Stages, in order. Each emits a structured log event (§9).


1. **Checksum & idempotency** — hash the file; if already ingested, skip and
   return a result flagged as skipped. Re-running after a crash is safe.
2. **Transcribe** — text segments with timestamps, no speakers yet.
3. **Diarize** — speaker turns with timestamps, no text.
4. **Align** — assign each transcript segment the diarized turn with the
   greatest time overlap; if a segment overlaps nothing, fall back to the
   nearest turn by start time. **Every segment ends up with a speaker;
   `None` is never acceptable.** *(High-risk — decide explicitly what
   happens on an exact overlap tie and on zero-duration segments.)*
5. **Chunk** — the merge-and-split strategy below. *(High-risk.)*
6. **Embed** — one batched call over all chunk texts; failures wrapped in
   the typed embedding error.
7. **Persist** — audio file record then chunks, in a single transaction so a
   partial write is impossible.


### Chunking strategy


**Merge**, then **split** (semantic-aware for long turns), then **link**.
Keep all tuning values in one place; the **soft minimum (~20s) and split cap
(~45s) are env-backed settings** (Q12), not literals — but **change them
only if a precision/recall problem is traced to chunking** (§10.5), never
speculatively. **Every cap must
keep chunks inside the embedder's 512-token window** (§17).


#### Step 1 — Merge (pure, no I/O)
Combine consecutive turns from the *same* speaker toward ~15s, hard-capped
at ~30s. **Never merge across a speaker boundary.** A no-op on rapid
alternating dialogue, which is expected and correct.


#### Step 2 — Split long turns at *meaning* boundaries


**Why this matters.** An 8–10 minute conversation contains monologues that
drift across two or three distinct topics. Cutting one at a fixed 45s mark
lands mid-topic roughly every time, producing two chunks that each contain
half of two ideas. Neither embeds cleanly, so neither ranks — and the answer
becomes unfindable even though it was transcribed perfectly. **This is the
single most common cause of "the text is in there but search can't find
it."**


Turns longer than the split cap (~45s) are cut at **semantic boundaries**:


1. Split the turn into sentences.
2. Embed the sentences (**one batched call per turn** — §0B.11).
3. Compute cosine similarity between each pair of *consecutive* sentences.
   Low similarity marks a topic shift.
4. Accumulate sentences. Once a **soft minimum** (~20s) is reached, every
   subsequent sentence boundary becomes a split *candidate*.
5. At the **hard cap** (~45s), split at the **lowest-similarity candidate
   seen so far** — the biggest topic change — not at the cap itself.


A 45–70s monologue moving from topic A to topic B is cut **exactly at the
drift point**, leaving two coherent, independently retrievable chunks.


**Non-negotiable safeguards:**
- **Deterministic fallback** on *any* embedder failure. A smarter split must
  never be the reason an ingest fails. Log at WARNING (§9).
- **Injected port only** — the `Embedder` domain port, never a concrete
  model. Unit-testable with a stub.
- **Determinism preserved** — this runs at *ingest*; the evaluated search
  path (Rule 8) is untouched.
- **Short turns are untouched.**


#### Step 2b — Deterministic split (the fallback, and the baseline)
Cut at sentence boundaries into sub-chunks capped at ~45s with a small
overlap (~2–3s). Word-level timestamps aren't available here, so
**apportion time across sentences proportionally to character length —
document this as a known approximation** in `SOLUTION.md`. Tested
independently: it is both the fallback and the comparison baseline.


#### Step 3 — Link
Store `prev_chunk_id` / `next_chunk_id` so a result can be displayed with
one chunk of context on each side.


#### Two functions, one behaviour contract
A **sync, embedder-free** chunker and an **async** chunker taking the
`Embedder` port. Both must produce identical output for any transcript whose
turns are all under the split cap. **Assert that in a test.**


---


## 7. Search — Two Branches, Weighted RRF Fusion


### Keyword branch


Run the **verbatim** user query against Postgres full-text search over a
generated, GIN-indexed `tsvector` column on chunk text.


**Stemming and normalization** are handled by the Postgres text search
configuration, applied identically on both sides:


- Use the **English** configuration (`english`) when generating the stored
  `tsvector` column and when parsing the query. Both sides **must** use the
  same configuration — a mismatch means the indexed lexemes and the query
  lexemes are produced by different rules, and matches are silently lost.
- That configuration applies the Snowball English stemmer and strips English
  stop words, so `"archiving"`, `"archived"`, and `"archives"` all reduce to
  a common lexeme and match each other. This is what makes the keyword
  branch tolerant of inflection without any custom logic.
- Because stemming is applied at index time via the **generated column**, it
  is consistent across every chunk by construction and cannot drift — never
  stem in application code.
- Word **positions** are retained in the stored vector; the ranking function
  below depends on them.


**Query parsing**: use a web-search-style parser so quoted phrases, `OR`,
and `-exclusions` behave as users expect, and so malformed input degrades
gracefully instead of raising.


**Ranking**: use a cover-density ranking function — it rewards query terms
appearing close together and in natural order, using the stored positions.
Enable **length normalization** (so a long chunk cannot win purely by
repeating a term) and **score saturation** (bounding scores to a predictable
range). Together these approximate BM25-style behaviour without a full BM25
implementation; note the difference in `SOLUTION.md`.


Return results already ordered best-first; the 1-based position of each row
is what fusion consumes, not the raw score.


**Known limitation to document**: stemming cuts both ways — it improves
recall on inflected forms but can conflate distinct technical terms that
share a stem. If a keyword query underperforms, check whether stemming
merged something it shouldn't have before assuming the fusion weights are
wrong.


### Semantic branch
Embed the query with the **same local model used at ingestion time**, then
run a pgvector cosine search. Order by the raw distance operator (not a
computed alias) so the ANN index is used. Convert distance to similarity so
both branches share a higher-is-better convention. Exclude chunks with a
missing embedding.


Both branches retrieve their own candidate list — the **top-K the caller
asked for is applied only after fusion**, never to individual branches.


### Fusion — Weighted Reciprocal Rank Fusion


A **pure function**. Input: a mapping of branch name → that branch's ranked
list, plus `k` and a per-branch weight map. Output: one ranked list of
(chunk id, fused score), highest first, sliced to top-K by the service.


*(High-risk — see Rule 10.)*


**The scoring rule.** For every chunk, its fused score is the **sum, over
each branch the chunk appears in, of that branch's weight divided by
(k + the chunk's 1-based rank within that branch)**.


Three properties that must hold, each with an explicit test:


- **Rank is 1-based and scoped to its own branch.** A chunk ranked 3rd in
  keyword and 7th in semantic contributes two separate terms.
- **The weight multiplies the per-branch contribution, not the final
  score.** Applying a weight after summing scales every branch identically
  and changes nothing — a silent no-op bug.
- **Absence contributes nothing.** No penalty, no zero-fill, no special case.


**Why rank-based rather than score-based** — state this in the design doc:
keyword ranking scores and cosine similarities live on different,
non-comparable scales, so fusing raw scores would need manual calibration
per query. Rank position is scale-free, which is exactly what makes
weighting *meaningful*: a weight expresses "how much do I trust this
branch's ordering," not an artefact of score magnitude.


**Why `k = 60`.** `k` smooths the gap between high and low ranks, so a
single branch cannot dominate purely by putting something first. It is the
commonly-cited default and a reasonable start for two branches of comparable
quality. Configurable, but leave it alone unless a measurement says
otherwise.


### Configurable branch weights


**Weights are configuration, not constants.** Both default to **1.0** —
equal weighting, the measured baseline (§0B.2).


| Requirement | Detail |
|---|---|
| **Where they live** | The env-backed settings object read **once at the composition root** (§5) |
| **How they reach fusion** | Injected into the search service at construction, passed to the pure fusion function per call. Fusion holds no state and reads no config |
| **Defaults** | Keyword 1.0, semantic 1.0. Documented in `.env.example` and `SETUP.md` |
| **Validation** | Reject negative or non-numeric weights at the boundary with a typed error (Rule 3). A weight of 0.0 is *legal* — it disables that branch, a useful diagnostic — but log a WARNING |
| **Unknown branch names** | A configuration error, not a silent no-op. Fail loudly |
| **Default on absence** | A branch in the rank lists but missing from the weight map gets 1.0 |
| **Per-request override** | **Not in scope.** No query parameter — it would make the evaluated path caller-dependent and non-reproducible |
| **Observability** | Log the active weights on every search request (§9) |


### Per-branch candidate depth


Each branch retrieves **more candidates than the final K** before fusion — a
chunk ranked 12th in one branch and 2nd in the other should still surface in
the top 10. Retrieve a **configurable** multiple of K per branch — an env-backed
setting (Q11), not a literal — and **apply the top-K slice only after
fusion**. The multiplier controls how deep each branch fetches, never where
the final cut happens. Slicing branches to K first
silently discards exactly the cross-branch agreements fusion exists to find.


### Tuning discipline — weights are configuration, not a way to pass


1. **Equal weights are the baseline.** Record the full §2 metric set at
   1.0 / 1.0 before changing anything. That row stays in `PROGRESS.md`
   permanently.
2. **Diagnose before weighting.** Use per-branch recall (§2) and the "which
   branch should have caught it" question (§0B.4). If keyword fails on
   paraphrase queries, that is *expected* — the fix may be chunking or
   embedding, not a weight.
3. **One change, re-measure, record both numbers** in the decisions log.
4. **Beware overfitting.** ~90 queries is small; a point or two may be
   noise. Prefer equal weights unless the gain is clear, consistent across
   *both* query types, and explainable by branch behaviour.
5. **Both precision and recall must improve** (Q13). A weight change that
   lifts recall while degrading precision — or that helps one query type at
   the other's expense — is **not** an improvement and gets reverted.
6. **Report honestly.** If the shipped config isn't 1.0 / 1.0, `SOLUTION.md`
   states the weights, the baseline, and the reasoning.


### Hydration
Fetch full records for only the top-K fused chunk ids, plus a deduplicated
set of audio-file lookups to resolve file names. Build result items carrying
chunk id, file name, speaker, truncated snippet, start/end time, fused
score. Defensively skip any id the repository cannot find.


### Boundary validation
Reject empty or excessively long queries with a typed error. Do **not**
silently truncate. Log a short hash of the query rather than the raw text at
INFO level.


---


## 7A. API Surface — Five Endpoints


Thin FastAPI layer over the application services. The API is the
**composition root**: it wires adapters, maps domain exceptions to HTTP
codes, and reads config once. It contains **no retrieval logic** — every
endpoint delegates to a service.


| Endpoint | Method | Purpose | Notes |
|---|---|---|---|
| `/ingest` | POST | Accepts a **list of files**; runs the pipeline per file | Idempotent per checksum |
| `/search` | GET | **The graded path.** Both branches → weighted RRF → top-K | Deterministic. Recall@k tests call this and only this |
| `/search/keyword` | GET | Keyword branch alone (tsvector + per-language stemming, §7B) | **Diagnostic only** |
| `/search/semantic` | GET | Semantic branch alone (pgvector cosine) | **Diagnostic only** |
| `/evaluation` | GET/POST | Runs the labeled query set; returns recall@5/@10, MRR, per-branch recall, speaker accuracy, latency percentiles | Long-running |


Tag routes `ingest`, `search`, `evaluation` so Swagger groups them. Every
route carries a response model, summary, description, and tag (§12).


### `/ingest` — accepts a list of files
- Takes **a list**, not one path. Process each file independently; **one
  failure must not abort the batch.**
- Return **per-file outcomes** — `ingested` / `skipped_existing` / `failed`
  with the stage and error type — plus chunk count and duration each. A
  partial success returns mixed per-file results, not a blanket 500.
- **Idempotency is per checksum** (§6.1). Re-posting the same files is safe
  and reports them as skipped.
- Validate every path at the boundary before starting any work (Rule 3).
- Synchronous by default. **Do not add a job queue** — that is gated (§11).


### `/search` — the only evaluated endpoint
Query text plus optional top-K. **No weight parameters** — weights are
deployment config (§7); a per-request override would make the evaluated path
caller-dependent, violating Rule 8. Returns file, timestamp, speaker,
snippet, and fused score per hit.


### `/search/keyword` and `/search/semantic` — diagnostic, not graded
These answer *"which branch should have caught this?"* (§0B.4) without a
debugger, and produce the per-branch recall that makes a weight decision
evidence-based (§7).


**Three rules, all binding:**
1. They must reuse the **exact same repository methods** as `/search`. A
   reimplementation that drifts makes the diagnosis worse than useless.
2. They must **never** be what evaluation calls for the primary metrics.
3. Their existence must not tempt anyone to move fusion into the API layer —
   it stays a pure function in `application`.


Mark both clearly as diagnostic in their route descriptions so a grader is
not misled about which endpoint is the deliverable.


### `/evaluation` — runs the suite, returns the numbers
- **Both GET and POST are supported** (Q14): GET for a quick no-body run in
  Swagger or a browser; POST for a body-parameterised run (a subset of the
  query set, a different top-K). **Both share one service method** — no
  divergent code paths, and neither mutates state.
- Runs the committed labeled query set through the search **service method**
  (not over HTTP), returning primary and secondary metrics together,
  **split by query type**.
- Include the **active fusion weights and RRF k** in the response. A metrics
  payload that doesn't say what configuration produced it is unusable
  evidence.
- Expect it to take much longer than a search request — say so in the route
  description.
- **It reports; it never writes.** No mutating `PROGRESS.md`, no tuning, no
  threshold logic. pytest remains the pass/fail authority (§10.2).


---


## 7B. Multilingual Support — COMPULSORY (Task 17)


**Status: required core scope, decided by the project owner on 2026-09-26.**
Not a stretch goal; the §11 gate does not apply. It amends Q2, Q4 and Q8
(§17). Where any other section, `HANDOFF.md` or `skiil.md` still says
English-only, **this section wins**.


**Requirement.** The system ingests two-speaker conversations in languages
other than English and searches them with the same guarantees as English:
every hit returns file, timestamp and speaker, `/search` stays
deterministic, and embeddings stay local. A query in one language should be
able to retrieve a chunk in another (cross-lingual semantic retrieval).
**English quality must not regress**: the English golden set (01–06) is the
regression baseline for every change in this section.


### What is language-dependent, and what is not

| Stage | Language-dependent? | Where today | Change |
|---|---|---|---|
| Decode | No | `infra/audio.py` | none |
| Transcribe | **Yes** | `infra/whisper.py` forces `language="en"` | M1 |
| Diarize | No — speaker identity is acoustic | `infra/diarizer.py` | none |
| Align | No | `application/alignment.py` | none |
| Chunk: sentence split | **Yes** | `application/chunking.py` `_SENTENCE_END` (Latin `.!?` + space only) | M3 |
| Embed + semantic split | **Yes** | `all-MiniLM-L6-v2` is English-only | M4 |
| Keyword branch | **Yes** | `db/schema.sql` + `infra/postgres.py` fix `english` | M5 |
| Fusion (RRF) | No — rank-based, language-free | — | none |
| Evaluation | **Yes** | English-only dataset; WER assumes spaces between words | M8 |


### M1 — Transcription: detect, don't force
- Remove the hard-coded `language="en"`. A new env-backed setting,
  `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE`, forces a language when set (ISO
  639-1, e.g. `en`, `hi`, `de`); **blank means auto-detect**. Validate it at
  the boundary (unknown code → `ConfigurationError`).
- Return the detected language **and its probability** from the
  `Transcriber` port (extend the port; do not read Whisper internals
  elsewhere). Log both at the `ingest.transcribe.end` event.
- Low detection confidence is **logged at WARNING and recorded**, never
  silently accepted. The threshold is a named constant, recorded in
  `PROGRESS.md` when chosen (Rule 2: do not invent it silently).
- Keep `temperature=0.0`, `beam_size=5` and `condition_on_previous_text=False`
  — determinism rules are unchanged.
- **Granularity: one language per file** (Whisper detects from the first
  30 s). Per-segment detection for code-switched speech is **only** added if
  the Q21 target data contains code-switching — then measure it, record it.
- `large-v3-turbo` is already multilingual; **no model change**. Turbo is
  weaker at *translation*, which this system does not use.

### M2 — Diarization and alignment: unchanged
Speaker turns are acoustic and alignment is pure time arithmetic. **Do not
touch them for this feature.** If speaker accuracy drops on non-English
audio, debug in pipeline order (§0B.3) before suspecting them.

### M3 — Chunking: script-aware sentence splitting
- `_SENTENCE_END` must also split on `。！？` (CJK, **no following space**),
  `।` `॥` (Devanagari), `؟` `۔` (Arabic/Urdu), in addition to `.!?` + space.
  A turn that never splits falls back to one oversized sentence — the exact
  failure §6 exists to prevent.
- Character-length time apportionment (§6 Step 2b) stays, and becomes a
  **documented approximation per script** in `SOLUTION.md` (characters carry
  different amounts of speech in Latin, CJK and Devanagari text).
- The split cap vs token window check (§17 consequences) is now **per
  language**: non-English text tokenizes into more tokens per second. Task 8
  asserts the max chunk token count < the model's window **for each
  language in the corpus**.

### M4 — Embeddings: a multilingual local model
- The English-only `all-MiniLM-L6-v2` is **replaced** by a local
  multilingual model. The same model drives the semantic splitter.
- **Final choice is Q22** and is made by measurement, not from memory.
  Candidates (figures NOT yet verified — **measure dimension and
  `max_seq_length` on the loaded model before touching the schema**, Rule 13):

  | Candidate | Expected dim | Expected window | Note |
  |---|---|---|---|
  | `intfloat/multilingual-e5-small` | 384 | 512 | **Recommended start.** Keeps `vector(384)`. Needs `query: ` / `passage: ` prefixes |
  | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | 128 | Window too small for a 45 s chunk. Avoid unless caps change |
  | `BAAI/bge-m3` | 1024 | 8192 | Strongest, heavier on CPU; schema → `vector(1024)` |

- **Asymmetric models need a port change**: the `Embedder` port must
  distinguish *query* embedding from *passage* embedding (prefixes live in
  the infra adapter only — never in application code). Ingest and the
  splitter use the passage side; the semantic search branch uses the query
  side. A missing or swapped prefix silently degrades recall — test it.
- A model change means: update `db/schema.sql` dimension if it differs,
  update the settings default, **drop and re-ingest everything**, record the
  before/after English recall.

### M5 — Keyword branch: per-chunk text search configuration
The rule "same configuration at index time and query time" (Q8, trap 1)
**still holds — per row** instead of globally.
- Add `chunk.language regconfig NOT NULL`. The generated column becomes
  `to_tsvector(language, text)`, so every row is stemmed by its own
  language's rules, by construction.
- One mapping, in **infra only**, from ISO code → Postgres configuration
  (`en→english`, `de→german`, `fr→french`, `es→spanish`, `hi→hindi`, …).
  **Verify each target exists** with `SELECT cfgname FROM pg_ts_config` on
  the real server — the list differs by Postgres version. An unmapped
  language falls back to `simple` (no stemming) **with a WARNING**; never
  silently to `english`.
- **Query side**: the query's language is unknown, so parse the query once
  per configuration present in the corpus, each pass filtered on
  `language = <that config>`, and merge the passes into one ranked list.
  This keeps index and query config equal on every row, and the GIN index
  still serves each pass. Ranks remain 1-based over the merged branch list
  (fusion rules §7 unchanged).
- **CJK (Chinese/Japanese/Korean) has no built-in Postgres config**, and
  `simple` cannot segment text written without spaces. How to handle it is
  **Q23**. Adding an extension (zhparser, pg_bigm, PGroonga) is a stack
  change and needs justification recorded first (§4B).
- The live-DB test that asserts `'english'::regconfig` in the generated
  column changes to assert the column uses `language`, and that each mapped
  config exists.

### M6 — Data model, settings, API
- `audio_file.language`, `audio_file.language_probability`, `chunk.language`
  (§8). Domain models `AudioFile`, `Chunk`, `SearchResultItem` gain
  `language`; **every search hit returns its language** alongside file,
  timestamp and speaker.
- Settings: `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE` (blank = auto) and the new
  `AUDIO_SEARCH_EMBEDDING_MODEL` default. The ISO → regconfig map is code in
  infra, not an env var. Update `.env.example` and `SETUP.md` (the
  `english`/`english` check becomes a per-language check).
- `/search` gets **no language parameter** in this task (keeps the graded
  path uncomplicated; retrieval across all languages). A filter is a later
  decision, recorded if added.

### M7 — Documentation
`SETUP.md` (new env var, per-language text-search check, model download
size), `SOLUTION.md` (languages supported, per-script apportionment
approximation, CJK handling, per-language results, English before/after),
`.env.example`.

### M8 — Evaluation per language
- The current dataset is **English only**, so multilingual behaviour cannot
  be measured yet. **Q21** decides the target languages and where the
  non-English audio + reference transcripts + labelled queries come from.
- Report every metric **split by language** (and still by keyword vs
  semantic query type). Add cross-lingual queries (query language ≠ chunk
  language) as their own slice.
- **CER is the primary transcription metric for languages written without
  spaces** (WER is meaningless there). Use Whisper's basic
  (non-English) normalizer for non-English WER/CER, not the English one.
- Whether the §2 primary thresholds apply **per language** is **Q24**
  (recommendation: yes). Until answered, report per-language numbers and do
  not claim a pass for a language that has none.

### Build order inside Task 17
1. M1 transcription + language stored (no retrieval change) — English
   re-ingest must produce the same text as before.
2. M3 sentence splitter (pure, unit-tested per script).
3. M4 embedder swap after Q22 measurement → re-ingest → English recall
   before/after recorded.
4. M5 per-chunk keyword config — **must land before or together with the
   Task 5 keyword branch**, so the branch is written language-aware once.
5. M8 evaluation once Q21 data exists.

### High-risk points in this section
- **Config mismatch, now per row** — the quietest failure gets more places
  to hide. Test a non-English stemmed match through the real column.
- **Embedding prefix asymmetry** (M4) — silent recall loss.
- **Fallback to `simple`** — must be visible (WARNING + count), never silent.
- **English regression** — measure English recall before and after every
  M-step; a drop is a defect, not a trade-off.


---


## 8. Data Model


### `chunk`
| Field | Purpose |
|---|---|
| `chunk_id` | Primary key (UUID) |
| `audio_file_id` | FK to source file |
| `speaker_id` | Which diarized speaker uttered this |
| `text` | Transcribed chunk text |
| `start_time` / `end_time` | Seconds into the file — satisfies the timestamp requirement |
| `embedding` | pgvector column, **`vector(384)`** — **the dimension must equal the multilingual model chosen under §7B / Q22**; re-verify and change it with that model |
| `language` | **§7B.** Postgres text search configuration (`regconfig`) for this chunk, derived from the file's detected language. Drives the generated tsvector |
| `prev_chunk_id` / `next_chunk_id` | Context stitching at display time |
| `token_count` / `char_count` | Chunking QA |
| `created_at` | Auditing / idempotency |
| `tsvector` | Generated column over `text` using **the chunk's own `language` configuration** (§7B; was fixed `english`), GIN-indexed |


### `audio_file`
`file_name`, `file_path`, checksum, duration, `created_at`. Joined on
`audio_file_id` to satisfy the "return the containing file" requirement.
**§7B adds** `language` (ISO 639-1 code from the transcriber) and
`language_probability` (detection confidence).


### Indexes
GIN on the tsvector column; **HNSW** on the embedding column (Q10). Record
the `m` / `ef_construction` used in `db/schema.sql`; expose query-time
`ef_search` as a setting so recall/latency can be traded without a reindex.


---


## 9. Logging & Observability


Structured JSON logging via the standard library, configured **once** at the
composition root. Calls live in the application layer at stage boundaries.
Cross-cutting, not a swappable port.


- **Ingestion**: start/end per stage with audio file id, duration, and
  counts (segments, speakers, chunks); a failure event with stage and error
  type. The chunk event records **how many long turns were split
  semantically vs. by deterministic fallback** — a rise in fallbacks means
  the embedder is failing quietly. For a batch ingest, log per-file outcomes
  plus a batch summary.
- **Search**: request event (query hash, requested top-K, **the active
  branch weights and RRF k**), per-branch completion (duration, candidate
  count), fusion completion, and a response event with **total duration and
  top result score**.


Logging the active weights per request is not optional: without it, a
ranking change caused by a config edit is nearly impossible to attribute.


Levels: INFO for stage/request events, WARNING for degraded results (empty
branch, semantic-split fallback, a 0.0 branch weight), ERROR for failures,
DEBUG for raw query text and full result sets (opt-in via env).


**Reuse for evaluation**: latency percentiles and **indexing throughput**
(§2, §10.4) both aggregate these events — no separate ad hoc timing code.


---


## 10. Evaluation Plan


*(High-risk — a bug that inflates a metric will not announce itself. Verify
the metric implementation against a tiny hand-computed example first.)*


### 1. Chunking quality (pre-retrieval sanity)
- Assert no chunk's text spans two diarized speaker turns.
- Length distribution over chunks; flag outliers.
- **Assert the two chunkers agree** on any transcript whose turns are all
  under the split cap (§6).
- **Report semantic vs. fallback split counts.** A high fallback rate means
  the semantic splitter isn't actually running.
- Spot-check start/end times against the source audio for drift.


### 2. Retrieval quality (the core evaluation)
- **Labeled query set**: ~15 queries per audio file, split into
  - *keyword* queries — exact phrases or named entities verifiable by
    grepping the transcript
  - *semantic* queries — paraphrases or conceptual questions avoiding the
    transcript's exact wording
- Each labeled with ground-truth relevant chunk ids from manual review.
- **Automated test**: pytest loads the query set, runs every query through
  the single-response search path, computes recall@5, recall@10 and MRR, and
  asserts against §2 thresholds. Report overall **and** split by query type.
- **Also record per-branch recall** (keyword-only, semantic-only,
  pre-fusion) — makes weight decisions evidence-based (§7) and shows whether
  fusion adds value over either branch alone.
- **Fusion unit tests** (no database, plain data): rank-1 beats rank-2
  within a branch; a chunk in both branches outranks one in a single branch
  at the same rank; changing a weight moves results in the expected
  direction; equal weights reproduce plain RRF; a 0.0 weight disables that
  branch; a chunk absent from a branch is neither penalised nor errored.
  Verify at least one case against a hand-computed score.
- **Keyword branch tests**: an inflected query form matches its stemmed
  indexed form, and the query-side and index-side configurations match.


### 3. Upstream quality — WER/CER, DER, speaker attribution
- **WER and CER** via `jiwer` (Q15): generated vs. reference transcript. The
  ceiling on everything. Report both — a high WER with a low CER means the
  transcript is closer than it looks and the gap is tokenization.
- **DER** via `pyannote.metrics` (Q15): diarized turns vs. reference turns.
  Using the reference implementation keeps the number consistent with the
  diarizer itself.
- **Speaker attribution accuracy**: predicted speaker on top-K vs.
  reference. **Align the predicted and reference label sets first** —
  diarizer ids are arbitrary per file.


Read together: high WER explains poor recall; high DER explains poor speaker
accuracy; **good DER with poor speaker accuracy points at the alignment step
(§6.4), not the diarizer.**


### 4. Latency and indexing throughput
- **Search latency**: aggregate response log events across a full query-set
  run on a warmed-up system; report p50/p95/p99, check p95 < 500 ms.
- **Indexing throughput**: aggregate `ingest.*` events into audio-minutes
  per wall-clock minute, **broken down by stage**. Report it; no threshold.


### 5. Failure-mode analysis (qualitative)
For queries missing threshold, classify root cause as chunking,
transcription (WER), stemming (collision or config mismatch), embedding, or
fusion — and name **which branch should have caught it** (§0B.4), using the
diagnostic endpoints (§7A). Document 2–3 representative cases in
`SOLUTION.md`. **This is the correct response to a missed target — not
threshold adjustment (Rule 16), and not reflexive weight-fiddling (§7).**


---


## 11. Deferred Stretch Goals — Gated, Ask Before Building


**Default state: not implemented.** Nothing below may start while any core
task (§13, Tasks 1–16) is unfinished.


### The gate — all four conditions, in order
1. **All core tasks Done** (Rule 18).
2. **All primary §2 criteria met and recorded.** If any target is missed,
   **fixing that miss is the work.**
3. **Time genuinely remains.**
4. **The user has been asked and has said yes** — to this specific item.


If 1–3 hold, **stop and ask the user**, listing what is unlocked and
recommending one. Do not pick for them. Do not start on assumed approval.


### Build order if approved
**One item at a time.** Finish, test, commit, update `PROGRESS.md` before
asking about a second.


| Priority | Item | Value if built | Cost / risk |
|---|---|---|---|
| 1 | LLM answer generation endpoint | Most visible demo value — natural-language answer citing file/speaker/timestamp | Must sit **outside** the evaluated search path |
| 2 | Streaming / SSE search endpoint | Perceived responsiveness | Must be a **separate method**, never a refactor of the evaluated one |
| 3 | Background job queue for ingestion | Production-readiness beyond 5–6 files | Operational surface, zero effect on retrieval quality |
| 4 | Relevance feedback loop | Would populate the fusion weight map from click data — the natural extension of §7 | No usage volume at this scale to shift rankings |
| 5 | Cross-encoder re-ranker | Potential precision gain | Direct threat to the p95 target |
| 6 | Query expansion / rewriting | Possible semantic recall gain | Unproven benefit, measurable latency cost |
| — | Embedding fine-tuning | — | **Not viable at this scale.** `SOLUTION.md` only |


**Note on item 4**: the weighted-RRF design (§7) is already the hook a
feedback loop would use. Say so in `SOLUTION.md`; do not build it.


### Non-negotiable when building any of them
- **The evaluated path must not change.** Stretch features are additive.
- **Re-run the full evaluation suite afterward.** Anything that moves a core
  metric gets reverted.
- **Record it** in the decisions log and `AGENT_LOG.md`.


### Always permitted, regardless of the gate
An LLM may be used **offline, as authoring assistance only**, to draft
candidate labeled-query-set entries. Every label human-verified. No LLM runs
inside the served system.


### Terminology
`async`/`await` is non-blocking I/O, **not** streaming. Both core services
return a single result per call.


---


## 12. Deliverables


| File | Contents |
|---|---|
| Git repo | All code, golden dataset, tests |
| `SOLUTION.md` | Design and rationale, success criteria, **achieved results including misses**, **final fusion weights and their baseline**, limitations, documented approximations, failure-mode cases |
| `AGENT_LOG.md` | Coding agent disclosure — required by the brief |
| `PROGRESS.md` | 1:1 mirror of §13 tasks, measured results, fusion config record, open questions, decisions log, known issues |
| `HANDOFF.md` | Resume point for a new session |
| `SETUP.md` | Clean-machine setup incl. fusion weight configuration (§4A) |
| `requirements.txt` / `requirements-dev.txt` | Pinned runtime and dev dependencies |
| `.env.example` / `.gitignore` | Env vars with placeholders, **including weights and RRF k** |
| `db/schema.sql` | Tables, per-chunk-language tsvector generated column (§7B; `english` for English), GIN + **HNSW** indexes, `vector(<dim of the chosen multilingual model>)` |
| Postgres + pgvector |
| Golden dataset | 5–6 audio files, 8–10 min, unique speaker pair each, with provenance and reference transcripts/speaker turns |
| Labeled query set | Committed as a data file, not embedded in test code |


### API documentation
FastAPI generates OpenAPI from type hints at no extra dependency cost. Set
app title/description/version at the composition root; give every route
(§7A) a response model, summary, description, and tag; add example values so
Swagger's "Try it out" works without setup. **Mark the two branch endpoints
as diagnostic** so a grader knows `/search` is the deliverable.


---


## 13. Task List


1. Bring the user-provided dataset into the repo: verify 5–6 files, 8–10 min
   each, unique two-speaker pair per file; record per-file provenance;
   preserve reference transcripts and speaker turns as ground truth
2. Set up the environment per §4A/§4B: venv, `requirements.txt`,
   `requirements-dev.txt`, `.env.example` (incl. weights and RRF k),
   `.gitignore`, first draft of `SETUP.md`
3. Scaffold the repo: `src/domain`, `src/infra`, `src/application`,
   `src/api`, `db/schema.sql` (`vector(384)` + `english` tsvector column),
; define all domain ports and the settings object
4. Implement the ingestion pipeline (transcribe → diarize → align → chunk →
   embed → index), including **both chunkers** (§6)
5. Implement the hybrid search service: keyword + semantic branches →
   **weighted RRF with configurable weights** → hydrated ranked top-K (§7)
6. Build the labeled query set (keyword + semantic, ground-truth chunk ids)
7. Implement automated recall@k / MRR tests, **plus per-branch recall,
   fusion unit tests, and keyword stemming tests** (§10.2)
8. Implement chunking QA regression tests (§10.1)
9. Implement WER/CER (`jiwer`), DER (`pyannote.metrics`), speaker accuracy,
   search latency (p50/p95/p99) and indexing throughput measurement
10. Run failure-mode analysis on sub-threshold queries; document cases
11. **Implement the five API endpoints (§7A)** with Pydantic models, route
    metadata, and app metadata for Swagger/ReDoc
12. Implement structured JSON logging across ingestion and search (**incl.
    active fusion weights per request**); wire latency and throughput to it
13. Finalize `SETUP.md` and verify it end to end on a clean clone
14. Write `SOLUTION.md`
15. Write `AGENT_LOG.md`
16. Maintain `PROGRESS.md` and `HANDOFF.md` throughout
17. **Multilingual support — compulsory (§7B)**: language detection + storage
    (M1), script-aware sentence splitting (M3), multilingual embedder (M4,
    Q22), per-chunk keyword configuration (M5), data model/settings/API (M6),
    docs (M7), per-language evaluation (M8, Q21/Q24). M5 lands **before or
    with** Task 5's keyword branch


---


## 14. Phasing


| Phase | Outcome | Tasks |
|---|---|---|
| **1 — Foundation** | Dataset in repo, environment reproducible, repo scaffolded, schema and containers up, ports and settings defined | 1, 2, 3 |
| **2 — Core Pipeline** | End-to-end ingest and weighted-RRF hybrid search working, **multilingual (§7B)**; first-pass recall@k | 4, 17 (M1–M6), 5, 7 |
| **3 — Evaluation & Hardening** | Real labeled query set, all QA checks, WER/DER/speaker/latency/throughput, per-branch recall, **per-language results**, failure analysis, the five endpoints, logging | 6, 8, 9, 10, 11, 12, 17 (M8) |
| **4 — Write-up** | Setup verified on a clean clone, design doc, agent disclosure, final progress state | 13, 14, 15, 16 |


Each phase is independently demoable. **Phase 2 alone already satisfies the
core problem statement.** Phase 3 is what makes it evaluated. Phase 4 is
what makes it submittable.


**Within Phase 2, build in this order:** deterministic chunker → full
pipeline end to end → semantic splitter on top → **equal-weight fusion
measured as the baseline** → only then consider any weight change.


---


## 15. Tracking Files — Bootstrap & Reuse Rule


Three files carry all resumable state: `HANDOFF.md`, `PROGRESS.md`,
`AGENT_LOG.md`. They are the memory of this project. Chat history is not.


### The rule, applied at the start of every session
**Check whether the file exists before doing anything with it.**
- **If it exists → use it. Never overwrite, never recreate, never reset it.**
  Recreating a tracking file destroys the project's history and is a defect.
- **If it does not exist → create it now**, using §15.1, before any
  implementation work. Populate it with the repo's *actual* state.


It is normal for `HANDOFF.md` and `PROGRESS.md` to exist while
`AGENT_LOG.md` does not yet.


### Every later session
1. Read `HANDOFF.md` → `PROGRESS.md` → the needed plan sections.
2. Verify against the actual repo. **The repo wins any disagreement.**
3. Do the work.
4. Update all three in place (§15.2), then commit.


### 15.1 Required structure when creating a file


| File | Must contain |
|---|---|
| `HANDOFF.md` | Read-me-first banner; start/end-of-session procedures; a **current resume point** naming the next task, blockers and first steps; a map of which plan sections each task needs; the `AGENT_LOG.md` template; the non-negotiables |
| `PROGRESS.md` | Last-updated date, current phase, repo state; §13 tasks under **Done / In Progress / Not Done** with a blocked-by column; environment status; API endpoint status; a measured-results table (primary and secondary); **a fusion configuration record**; open questions with decision + rationale; an **append-only decisions log**; known issues; a session index |
| `AGENT_LOG.md` | One append-only entry per session using the §16 template |


Task numbers are stable. **Never renumber them.**


### 15.2 Update discipline
- **Done** only when all four conditions in Rule 18 hold. Partial work goes
  to **In Progress** with a note on what remains.
- Move a task **in the session that changes its state**.
- Record metrics as measured, including misses. Leave `—` for anything not
  measured; never estimate.
- **Any fusion weight change is recorded with before/after metrics** (§7).
  The equal-weight baseline row is permanent.
- **Every install is recorded** (§4B): what, why, which requirements file.
- Every non-obvious choice and every deviation goes in the decisions log.
- **Anything surprising gets recorded** (Rule 15) — Known Issues if
  unresolved, Decisions Log if resolved.
- `AGENT_LOG.md` entries are append-only.
- **No session ends without**: updating `PROGRESS.md`, appending to
  `AGENT_LOG.md`, refreshing the `HANDOFF.md` resume point, and committing.


---


## 16. Agent Session Protocol


Assume every session starts with **no memory of prior sessions** and
possibly a **different model**. All resumable state lives in files.


1. **Open with `HANDOFF.md`**, then `PROGRESS.md`, then only the plan
   sections the task needs.
2. **Activate the venv** before running anything (§4A).
3. **One phase per session.**
4. **The repo is the source of truth.**
5. **Close every session** by updating `PROGRESS.md`, appending to
   `AGENT_LOG.md`, updating `HANDOFF.md` §4, and committing.
6. **Reference files by path, don't re-paste them.**


### `AGENT_LOG.md` entry template
```
## Session <N> — <date> — Phase <N>
Model/agent: <which model or tool ran this session>
Prompt summary: <what you were asked to do, in 1–2 lines>
Key decisions: <bullets — anything a future agent must not contradict>
Deviations from PLAN: <what you did differently and why; "none" if none>
Packages installed: <name==version and which requirements file — §4B>
Files touched: <list>
Verified how: <what you actually ran to confirm it works — Rule 13>
Open items left: <what the next session must pick up>
```


---


## 17. Resolved Decisions — Locked Stack


**Settled**; do not relitigate. Full rationale in `PROGRESS.md` → Open
Questions. If evidence emerges that one is wrong, record the change in the
decisions log with its reason — never change one silently.


| # | Decision | Key constraint it imposes |
|---|---|---|
| Q1 | **Dataset**: user-provided synthetic two-speaker audio | Copyright-safe to commit. Reference transcripts and speaker turns exist → exact ground truth for WER, DER, speaker accuracy |
| Q2 | **Transcription**: Whisper `large-v3-turbo` via faster-whisper, local | MIT-licensed, ~5× faster than large-v3 at near-identical accuracy. Fallback `small` if hardware struggles. Requires `ffmpeg` |
| Q2a | **Amended 2026-09-26 (§7B M1)**: language is **auto-detected** (setting `AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE`, blank = auto), no longer forced to `en` | Detected language + probability stored per file; determinism settings unchanged |
| Q3 | **Diarization**: `pyannote/speaker-diarization-3.1` | MIT, commercial use permitted. **Gated** — accept conditions on both `speaker-diarization-3.1` *and* `segmentation-3.0`, supply an HF token. Mono 16 kHz. Pass `num_speakers=2` |
| Q4 | **Embeddings**: `all-MiniLM-L6-v2`, **384-dim**, local | Schema column is `vector(384)`. 512-token limit must stay above the chunk caps in §6. Also drives the semantic splitter |
| Q4a | **Superseded 2026-09-26 (§7B M4)**: the embedder must be **multilingual**; `all-MiniLM-L6-v2` is English-only. Final model = Q22, chosen by measurement | Schema dimension follows the chosen model; asymmetric models need query/passage embedding in the port; full re-ingest |
| Q5 | **Query set**: ~90 queries (15 × 6 files), 50/50 keyword/semantic | LLM-drafted, **every label human-verified**. Disclose in `AGENT_LOG.md` |
| Q6 | **Chunking**: semantic-boundary splitting for long turns, deterministic fallback | Long turns drift across topics; a fixed-offset cut lands mid-topic and makes content unfindable. See §6 |
| Q7 | **Fusion**: weighted RRF, per-branch weights from config, defaulting to 1.0 / 1.0 | Config read once at the composition root — never a query parameter. Equal weights are the permanent measured baseline. See §7 |
| Q8 | **Keyword branch**: Postgres FTS with the `english` configuration, stemming via the generated tsvector column | The **same configuration at index time and query time**. Never stem in application code. See §7 |
| Q8a | **Amended 2026-09-26 (§7B M5)**: configuration is **per chunk** (`chunk.language regconfig`), generated column `to_tsvector(language, text)`; the query is parsed once per configuration present, filtered to matching rows | "Same config at index and query time" still holds, per row. Unmapped language → `simple` + WARNING. CJK = Q23 |
| Q9 | **API surface**: five endpoints — `/ingest` (list), `/search` (graded), `/search/keyword` and `/search/semantic` (diagnostic), `/evaluation` | Branch endpoints reuse the same repository methods and are never the graded path. See §7A |


### Consequences to honour while building
- **Schema**: embedding dimension `384` must match the model. A mismatch
  fails at insert time, not query time.
- **Text search configuration must match** on the generated column and the
  query parser — **per row** since §7B (each chunk's `language`). A mismatch loses matches silently, with no error.
- **Chunk caps vs token limit**: the ~45s split cap must keep chunks inside
  the 512-token window. If a cap is raised, re-verify.
- **Semantic splitting must never break ingestion** — deterministic fallback
  on any embedder failure, logged at WARNING, count reported (§10.1).
- **Fusion weights are config, not code.** Defaults 1.0 / 1.0, validated at
  the boundary, logged per request, never a query parameter, never changed
  without a before/after measurement.
- **Branch candidate depth exceeds top-K.** Slice to K only after fusion.
- **`/search` is the only graded endpoint.**
- **A batch ingest isolates failures per file.**
- **Speaker label alignment**: align predicted to reference labels before
  scoring §10.3.
- **Missing packages get installed, pinned, and recorded** (§4B) — never
  stubbed, skipped, or worked around.
- **`SETUP.md` must document** the gated-model setup, the fusion
  configuration variables, the text search configuration check, and every
  system-level prerequisite (`ffmpeg`).
- **`SOLUTION.md` must disclose** the synthetic-audio limitation (no
  crosstalk, overlap, room noise, accent variety — so WER and DER read
  better than production) **and the final fusion weights with their
  baseline.**


### Q10–Q15 — Previously open, now decided


| # | Decision | Constraint it imposes |
|---|---|---|
| Q10 | **Vector index: HNSW** (not ivfflat) | Better recall-at-speed than ivfflat and no training step, so it works on an empty table and stays correct as rows are added. Index build parameters (`m`, `ef_construction`) and the query-time `ef_search` are **configurable** — start at the extension defaults, change only with a measurement |
| Q11 | **Per-branch candidate depth multiplier: configurable** | An env-backed setting, not a literal. Default to a small multiple of K. **Still slice to top-K only after fusion** — the multiplier controls how deep each branch fetches, never where the final cut happens |
| Q12 | **Semantic-split soft minimum and cap: configurable, default ~20s / ~45s** | Env-backed named constants. **Change only if a precision/recall problem is traced to chunking** (§10.5), never speculatively. Any change must keep chunks inside the embedder's 512-token window (Q4) |
| Q13 | **Fusion weights: change only if both precision and recall improve** | Beyond the §7 tuning discipline: a weight change that lifts recall while degrading precision (or either query type) is **not** an improvement and gets reverted. Equal weights stay the shipped default unless the evidence is unambiguous |
| Q14 | **`/evaluation` supports both GET and POST** | GET for a quick no-body run in Swagger or a browser; POST for a body-parameterised run (e.g. a subset of the query set, a different top-K). **Both share one service method** — no divergent code paths, and neither mutates state |
| Q15 | **Metrics libraries: `pyannote.metrics` for DER, `jiwer` for WER and CER** | Both pinned in `requirements-dev.txt` (evaluation-only, not runtime). `pyannote.metrics` is the reference DER implementation and is already consistent with the diarizer (Q3). `jiwer` gives WER **and CER** from one dependency — CER is the more forgiving read when WER is inflated by tokenization rather than genuine mishearing |


### Consequences of Q10–Q15


- **HNSW is built on the embedding column** in `db/schema.sql` (§8). Record
  the chosen `m` / `ef_construction` there; expose `ef_search` as a setting
  so recall/latency can be traded at query time without a reindex.
- **Four things are now env-backed settings**, read once at the composition
  root alongside the fusion weights (§5, §7): HNSW `ef_search`, the
  candidate depth multiplier, the semantic-split soft minimum, and the
  split cap. None of them may be read inside a service.
- **Defaults ship unchanged.** Q11–Q13 all say *configurable, but do not
  tune without evidence*. The baseline run (§0B.2) uses every default; a
  changed value needs a before/after measurement in the decisions log.
- **`jiwer` and `pyannote.metrics` are dev dependencies**, not runtime — the
  served system never imports them. Add both in the same session they are
  first used, per §4B.
- **CER is reported alongside WER** (§2 secondary). When WER looks bad but
  CER is fine, the transcript is closer than the number suggests and the
  gap is tokenization; that distinction changes where you look next.


### Still genuinely open


| Item | Decide by |
|---|---|
| HNSW `m` and `ef_construction` values | Task 3 — start at the extension defaults; record what was used |
| Default value of the candidate depth multiplier | Task 5 — a small multiple of K; record it |


