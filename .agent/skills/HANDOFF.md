# HANDOFF.md — Resume Point


> **Read this file first, before anything else in the repo.**
>
> This project is built across multiple sessions, possibly by different AI
> agents or different models. Assume you have **no memory of prior sessions
> and no access to earlier conversations.** Everything you need to resume is
> in the repo files. Nothing important lives in chat history.


---


## 1. What this project is


Hybrid (keyword + semantic) search over 5–6 two-speaker audio conversations,
8–10 minutes each. A search must return, for every hit: the **containing
file**, the **timestamp**, and the **speaker**. The two branches are
combined with **weighted RRF** and sliced to top-K, exposed over **five
FastAPI endpoints** (§7). Success is measured by automated recall@k tests
against a labeled query set.


Full specification: `PLAN.md`.


---


## 2. Start-of-session procedure


Follow these steps in order. Do not skip ahead to writing code.


0. **Check the three tracking files exist**: `HANDOFF.md`, `PROGRESS.md`,
   `AGENT_LOG.md`. **If a file exists, use it — read and update it in place,
   never overwrite or recreate it.** If one is missing, create it now using
   `PLAN.md` §15.1, populated with the repo's *actual* current state.
1. **Read this file** — the current resume point (§4 below).
2. **Read `PROGRESS.md`** — what is Done, In Progress, Not Done; the
   environment, installed-packages and endpoint status; the fusion
   configuration record; the open questions; the decisions already made.
   Treat the Decisions Log as binding.
3. **Activate the virtual environment.** If `.venv/` does not exist yet,
   create it and follow `PLAN.md` §4A. **Never install into the system
   interpreter; never run a script outside the venv.**
4. **Read only the `PLAN.md` sections your assigned task needs**, and
   **always §0 (Rules) and §0B (Engineering Standard)**. Map in §5 below.
5. **Inspect the repo** to confirm reality matches `PROGRESS.md`. If they
   disagree, **the repo is the truth** — correct `PROGRESS.md` first.
6. **Confirm the task**: state which numbered task from `PLAN.md` §13 you
   are doing and what "done" means for it. If it touches one of the four
   high-risk areas (§10), plan the logic and edge cases *before* coding.


---


## 3. End-of-session procedure


**Never end a session without doing all five.** An undocumented session is
lost work — the next agent will redo it or contradict it.


1. **Update `PROGRESS.md`**: move tasks between Done / In Progress / Not
   Done; update the Environment, Installed Packages and API Endpoint Status
   tables; fill in any metrics measured (primary *and* secondary); **update
   the Fusion Configuration Record if weights or k changed**; record any
   decision in the Decisions Log; add any new open question or known issue —
   **including anything surprising**.
2. **If you installed anything**, pin it in the right requirements file, add
   a row to the Installed Packages Log, and update `SETUP.md` if a fresh
   clone now needs a new step (§4B).
3. **Append to `AGENT_LOG.md`** using the template in §6. Include **how you
   verified** the work and **what you installed**, not just what you touched.
4. **Update §4 of this file** so the next agent's resume point is accurate.
5. **Commit.** Uncommitted work does not exist to the next session.


---


## 4. ▶ CURRENT RESUME POINT


**Update this section at the end of every session.**


**Last session:** 2026-09-26 (Task 11: FastAPI endpoints & live server)
**Repo state:** Tasks 1, 2, 3, 4, 5, 7, and 11 are **Done**. `src/api/main.py` created with all 5 endpoints (`/ingest`, `/search`, `/search/keyword`, `/search/semantic`, `/evaluation`). Unit tests in `tests/unit/test_api.py` pass (155 unit tests passing across repo). Live server running on port 8000.
**Task 11: Done.** FastAPI app created in `src/api/main.py`, tested with unit tests and live HTTP calls (`curl http://localhost:8000/docs` -> 200 OK, `/search` returns hydrated result items with `language`, `score`, `speaker`, `file_name`, `timestamps`).

**Never evaluate timestamps against the uncorrected `dataset/audio_*.json`. Use `dataset/reference_corrected/`.**


**Locked stack:** Whisper `large-v3-turbo` via faster-whisper (local) ·
`pyannote/speaker-diarization-3.1` (gated, needs HF token) ·
`all-MiniLM-L6-v2` at **384 dimensions** · Postgres + pgvector ·
Postgres FTS with the **`english`** configuration · **HNSW** vector index ·
FastAPI · **weighted RRF, k=60, weights default 1.0 / 1.0 from config** ·
`jiwer` (WER/CER) + `pyannote.metrics` (DER), dev-only.


**Five env-backed settings**, read once at the composition root: RRF `k` ·
branch weights · HNSW `ef_search` · per-branch candidate depth multiplier ·
semantic-split soft minimum and cap. **All ship at defaults** — change any
of them only with a before/after measurement.


**⚠️ Two agents are active (user decision, 2026-09-26):** the external agent owns **Task 11** (`src/api/main.py`, `tests/unit/test_api.py`); the Claude Code agent owns **Task 17**. Task 17 is changing `SearchResultItem`/`AudioFile`/`Chunk` (a new `language` field), `settings.py`, `container.py`, the schema (a `language` column now, then `vector(1024)` and a per-row keyword config), and `postgres.py`. **The API must pass `language` through and must add no language or weight query parameters.** Commit only your own paths.

**Next task:** Task 17 (multilingual, user-confirmed; checklist `MULTILINGUAL_UPDATE_PLAN.md`; step 1 baseline done) starting at M1. **Blocked on the user:** human verification of `dataset/queries/en.review.md` (Task 6). Primary misses so far: semantic recall (0.60/0.67). Diagnose them (Task 10) **after** the M4 embedder swap, since bge-m3 changes the semantic branch; compare English before/after. Run the eval with `python scripts/evaluate.py` or `pytest -m eval`. Task 4 is Done: the DB holds run 3 (313 chunks, word-level alignment). Re-ingest with `python scripts/ingest.py` (≈ 25 min, CPU-heavy). Old runs are snapshotted in `logs/chunks-run{1,2}-*.json` (gitignored). **Do not use the `AUDIO_SEARCH_ANSWER_*` / NVIDIA / OpenAI vars in the user's `.env`**: they are stretch item #1 and the gate is closed.


**Do this next:**
1. `source .venv/bin/activate`, then `python -m pytest` (expect 78 passed; needs Postgres running). **Before Task 4:** read `PROGRESS.md` Known
   Issues. The duplicate-FFmpeg warning means ingestion should decode each file once.
   The embedder limit is 256 tokens, not 512.
2. **Task 2** — set up the environment per `PLAN.md` §4A/§4B: `.venv/`,
   `requirements.txt` and `requirements-dev.txt` (pinned), `.env.example`
   (**including the fusion weight and RRF k variables**), `.gitignore`,
   first draft of `SETUP.md`. **Install whatever is missing** — including
   system tools — and log each one. Complete the **gated-model setup** now:
   accept conditions on both `pyannote/speaker-diarization-3.1` and
   `pyannote/segmentation-3.0`, create an HF access token, supply it via
   env, document it in `SETUP.md`. Confirm **`ffmpeg`** is installed.
3. **Task 3** — scaffold the four layers, define every domain port and the
   env-backed settings object (**including fusion weights and k**), write
   `db/schema.sql` with the embedding column as **`vector(384)`** and the
   **tsvector generated column using the `english` configuration**, a GIN
   index on it and an **HNSW index on the embedding column** (record the
   `m` / `ef_construction` used),  Postgres +
   pgvector. Define the settings object with all **five** configurable
   values.


**Blockers:** None. Every prerequisite decision is made.


**When you reach Phase 2, build in this order:** deterministic chunker →
full pipeline end to end → semantic splitter on top → **equal-weight fusion
measured as the baseline** → only then consider any weight change (§8).


**Do not start** any item in `PLAN.md` §11 (Deferred Stretch Goals). Core
work is unfinished, so the gate is closed.


---


## 5. Where to find what in `PLAN.md`


Load only what the task needs. **§0 (Rules) and §0B (Engineering Standard)
are required for every task.**


| If your task is… | Read `PLAN.md` sections |
|---|---|
| Any task at all | **§0 Rules**, **§0B Engineering Standard**, §2 Success Criteria |
| Task 1 — dataset | §1 Problem Statement, §17 Resolved Decisions |
| Task 2 — environment | §4A Environment & Setup, **§4B Missing Packages**, §7 (config vars), §17 |
| Task 3 — scaffold | §5 Architecture, §8 Data Model, §4 Stack, §7 (settings + tsvector config) |
| Task 4 — ingestion + chunking | §6 Ingestion Pipeline (esp. Chunking), §8, §9 |
| Task 5 — search + weighted fusion | **§7 Search in full**, §8, §9 |
| Tasks 6, 7, 10 — evaluation | §10 Evaluation Plan, §2, §7 (tuning discipline) |
| Task 8 — chunking QA | §10.1, §6 Chunking |
| Task 9 — WER/DER/latency/throughput | §10.3, §10.4, §2, §9 Logging, §4B (scoring library) |
| Task 11 — API endpoints | **§7A API Surface in full**, §12 (API documentation) |
| Task 12 — logging | §9 Logging & Observability, §7 (weights per request) |
| Task 13 — setup verification | §4A, §4B, §12 Deliverables |
| Tasks 14, 15 — write-up | §2, §7, §10, §11, §12, plus `PROGRESS.md` tables |
| Any §11 stretch item (only if gate open) | §11 in full, plus §2 |


---


## 6. `AGENT_LOG.md` entry template


Append one entry per session. Never edit or delete past entries.


```
## Session <N> — <date> — Phase <N>
Model/agent: <which model or tool ran this session>
Prompt summary: <what you were asked to do, in 1–2 lines>
Key decisions: <bullets — anything a future agent must not contradict>
Deviations from PLAN: <what you did differently and why; "none" if none>
Packages installed: <name==version and which requirements file — §4B>
Files touched: <list>
Verified how: <what you actually ran to confirm it works>
Open items left: <what the next session must pick up>
```


---


## 7. API surface — five endpoints


Full spec: `PLAN.md` §7A. The API is the composition root and holds **no
retrieval logic** — every endpoint delegates to a service.


| Endpoint | Method | Purpose |
|---|---|---|
| `/ingest` | POST | Accepts a **list of files**; per-file outcomes; **one failure must not abort the batch**; idempotent per checksum |
| `/search` | GET | **The graded path.** Both branches → weighted RRF → top-K. **No weight parameters** |
| `/search/keyword` | GET | Keyword branch alone — **diagnostic only** |
| `/search/semantic` | GET | Semantic branch alone — **diagnostic only** |
| `/evaluation` | **GET + POST** | Runs the labeled query set via the service method; returns all metrics **plus the active weights and k**. GET for a quick no-body run, POST for a parameterised one — **one shared service method**. Reports only, never writes |


**Three binding rules for the branch endpoints**: they reuse the **exact
same repository methods** as `/search`; they are **never** what evaluation
calls for primary metrics; and they must not pull fusion into the API layer.


---


## 8. Fusion — weighted RRF with configurable weights


Full spec: `PLAN.md` §7.


**Scoring rule**: each chunk's fused score is the **sum, over each branch it
appears in, of that branch's weight divided by (k + its 1-based rank within
that branch)**. Sort descending, slice to top-K.


**Three properties that must hold — test each:**
1. Rank is **1-based and scoped to its own branch**.
2. The weight multiplies the **per-branch contribution**, not the final
   score. Weighting after summing changes nothing — a silent no-op bug.
3. **Absence contributes nothing** — no penalty, no zero-fill.


**Configuration**: defaults **1.0 / 1.0**; env-backed settings read once at
the composition root; injected into the search service; passed per call to
the pure fusion function. Validate at the boundary (negative → typed error;
`0.0` legal but logs WARNING; unknown branch → fail loudly; missing → 1.0).
**Never a query parameter.** **Log active weights every request.**


**Candidate depth**: each branch retrieves more than K; **slice to top-K
only after fusion.**


**Tuning discipline**: equal weights are the permanent baseline — measure it
first. Diagnose with per-branch recall before touching a weight. One change,
re-measure, record both numbers. **A change must improve both precision and
recall** — lifting recall while degrading precision, or helping one query
type at the other's expense, is not an improvement and gets reverted.
**Beware overfitting** — ~90 queries is small. Disclose any non-default
weights in `SOLUTION.md`.


---


## 9. Keyword branch — stemming via the `english` configuration


Full spec: `PLAN.md` §7.


Stemming is handled by **Postgres**, not application code. Use the
**`english`** configuration **identically on both sides** — generating the
stored `tsvector` column *and* parsing the query.


> **A configuration mismatch is the quietest failure in this branch.**
> Indexed and query lexemes get produced by different rules, matches vanish,
> and nothing errors. Verify both sides explicitly.


- Snowball stemming + stop-word removal, so inflected forms match each other
  with no custom logic.
- Stemming happens at index time via the **generated column** — consistent
  by construction, cannot drift. **Never stem in application code.**
- **Positions are retained** — cover-density ranking depends on them.
- **Known tradeoff**: stemming can conflate distinct technical terms sharing
  a stem. **Check for a collision before blaming the fusion weights.**


---


## 10. Care over speed — the four high-risk areas


`PLAN.md` §0 Rules 9–18 govern *how* to implement. **Speed is not a success
criterion; correctness is.**


| Area | Why it's dangerous |
|---|---|
| **Alignment** (`PLAN.md` §6.4) | Off-by-one and overlap-tie errors silently corrupt every speaker label; invisible until evaluation |
| **Chunking** (§6) | Boundary and time-apportionment bugs misplace timestamps — a direct violation of the core requirement |
| **Fusion** (§7) | Ranks must be 1-based and per-branch, and weights must multiply the *per-branch* term. Errors still look plausible while degrading recall |
| **Evaluation** (§10) | A bug that *inflates* a metric never announces itself. Verify against a hand-computed example |


---


## 11. Chunking — the highest-leverage part of the pipeline


Full spec: `PLAN.md` §6. Long conversational turns drift across two or three
topics. Cutting one at a fixed 45s mark lands mid-topic nearly every time,
producing two chunks that each hold half of two ideas — neither embeds
cleanly, so neither ranks. **This is the most common cause of "the text is
in there but search can't find it."**


**Three steps**: merge same-speaker runs (~15s target, ~30s cap, never
across a speaker boundary) → split long turns at *meaning* boundaries →
link prev/next.


**The semantic split**: sentence-split the turn, embed sentences in one
batched call per turn, compare consecutive sentences, and past a ~20s soft
minimum treat every sentence boundary as a split candidate. At the ~45s cap,
split at the **lowest-similarity candidate** — the biggest topic change.


**Four safeguards, all non-negotiable:** deterministic fallback on any
embedder failure (WARNING + counted) · injected `Embedder` port only ·
ingest-time only, so the evaluated path stays deterministic · **both
chunkers must agree below the cap**, asserted in a test.


---


## 12. Engineering standard — work as a principal RAG engineer


`PLAN.md` §0B in full. Condensed:


- **Retrieval quality is the product.**
- **Measure before you optimize.** Baseline first; one variable at a time.
  **For fusion the baseline is equal weights.**
- **Debug in pipeline order** — transcription → diarization/alignment →
  chunking → embedding → branches → fusion. **WER and DER exist to turn "is
  the upstream good?" into a number**, and the branch endpoints (§7) exist
  to answer "which branch should have caught this?"
- **Know which branch should have caught a failed query.**
- **Design for the swap, not the rewrite.** No infra type leaks upward; the
  pure core stays pure; config read once at the composition root; the API
  layer holds no retrieval logic.
- **Make the system explain itself** — structured logs at stage boundaries,
  including active fusion weights.
- **Short if short is still obvious**; explicit in the high-risk areas.
- **Optimize search, not ingestion.**
- **Minimal ceremony**, but **keep** type hints on domain ports, public
  service methods, FastAPI routes and Pydantic models (Swagger is generated
  from them), brief docstrings on high-risk functions, and *why* comments.
- **State limits specifically.** **Taste is knowing what not to build.**


---


## 13. Non-negotiables


- **Always work inside the venv.** No system-wide installs.
- **If something is missing, install it — then pin and record it** (§4B).
  Never stub it out, never skip the test, never leave a "not available in
  this environment" note. But never silently either: pinned in the right
  requirements file, logged in `PROGRESS.md`, `SETUP.md` updated if a fresh
  clone needs a new step. **Anything that changes the approved stack needs
  justification recorded first.**
- **Build only what `PLAN.md` §3 scopes.** §11 items stay unbuilt until the
  gate opens: all core tasks Done, all **primary** §2 criteria met and
  recorded, time remaining, **and explicit user approval** for that item.
- **Primary thresholds are fixed.** If a primary target is missed, diagnose
  the cause (§10.5) — **never lower a threshold, hand-pick the query set,
  or special-case the evaluation.** **Fusion weights are config, not a way
  to pass** — any change needs a before/after measurement recorded.
- **Never assume a default.** Ambiguity goes to `PROGRESS.md` Open
  Questions, surfaced — not guessed.
- **Verify, don't assume.** "It should work" is not a verification.
- **Done means all four**: code exists, tests pass, it ran against real
  data, and it is committed.
- **`GET /search` is the only graded endpoint**, and it stays deterministic
  — one complete result set per query, no streaming, no generative model, no
  randomness, **no per-request weight overrides.**
- **Embeddings are generated and indexed locally.** Hard constraint.
- **Layer dependencies point inward only**: `api → application → domain`,
  `infra` implements ports. Application code never imports infra and never
  contains SQL. **The API layer holds no retrieval logic.**
- **Tracking files are append/update-only.** Recreating one destroys the
  project's history and is a defect.
- **The repo is the source of truth**, not chat history, not memory.
- **Record honest results.** A documented miss with root cause is worth more
  than a blank cell or an inflated number.


---


## 14. Four known traps


1. **Text search configuration mismatch.** If the tsvector column and the
   query parser use different configurations, stemmed lexemes won't line up
   and matches disappear **with no error**. Verify both sides.
2. **Diarizer speaker ids are arbitrary per file.** Align predicted to
   reference labels before scoring speaker accuracy, or a correct
   diarization scores near zero.
3. **The 256-token embedder limit** (measured; `PLAN.md` says 512, which is wrong) must stay above the chunk size caps in
   `PLAN.md` §6. Re-verify if a cap changes.
4. **Slicing branches to K before fusion** silently discards the
   cross-branch agreements fusion exists to find.
