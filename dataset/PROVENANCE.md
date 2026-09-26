# Dataset Provenance — Synthetic Two-Speaker Golden Audio Dataset

Task 1 (`PLAN.md` §13). Verified 2026-09-26 with `ffprobe`, `ffmpeg silencedetect`
and `jq` against the files as supplied. **Original files are unmodified** — the
checksums below are the ground-truth identity of each file.

## Source

| Field | Value |
|---|---|
| Name (from JSON `dataset` field) | Synthetic Two-Speaker Golden Audio Dataset |
| Supplied by | Project owner (user-provided), placed in `dataset/` on 2026-09-24 |
| Nature | Synthetic (TTS-generated) two-speaker technical design conversations — no real speakers, no third-party copyright (`PROGRESS.md` Q1) |
| Generator / TTS engine / voices | **Unknown — Open Question Q20** |
| Speaker labels | `SPEAKER_00` / `SPEAKER_01` in every file |

## Files

All audio: WAV, `pcm_s16le`, **22 050 Hz, mono**. Audio duration (ffprobe) equals
the JSON `duration_seconds` to 0.01 s for every file.

| audio_id | Topic | Duration (s) | Segments | Words | Talk s (S00 / S01) | WAV sha256 |
|---|---|---|---|---|---|---|
| audio_01_rate_limiter | Distributed Rate Limiter | 442.08 | 56 | 1302 | 202.1 / 228.0 | `9aa13f2f6ca27812d7ded9c12dcb6ba6160f7402edd20c230cd21095f7328a2c` |
| audio_02_url_shortener | URL Shortener at Scale | 386.45 | 52 | 1093 | 172.6 / 202.7 | `0bb38f644593dd055011960c545952653d8ed748577a08c98297292b9c596af9` |
| audio_03_chat_system | Real-Time Chat and Messaging System | 365.84 | 51 | 1039 | 180.1 / 174.8 | `ca0c89b74804d1156c747c18aca353c5f5194e7fa0047ddc7417b893a84522c7` |
| audio_04_news_feed | Social News Feed Ranking and Fanout | 356.09 | 50 | 1026 | 172.2 / 173.2 | `e8593efe83c6f0ade1d29641675892f5272d25787b4b9be7aaab5f0d8b56227a` |
| audio_05_payment_idempotency | Payment Processing and Idempotency | 379.86 | 54 | 1044 | 177.1 / 191.2 | `936a5113827d48360e0596dc373f86b4956f31ae4d8d6fad5fe76e67a6adccb9` |
| audio_06_video_streaming | Video Streaming and Delivery Pipeline | 353.24 | 50 | 919 | 161.4 / 181.2 | `d682707039e5c37d50ab1bfb7883ea1c5c5d50ed006e3b112e8727bdde4c5421` |
| audio_07_distributed_cache | Distributed Cache Design | 345.96 | 52 | 975 | 161.5 / 173.4 | `f55b39233d397d89bb7de124eea6a4c45c7538b810aff2a938a1ba330c654e81` |
| audio_08_ride_dispatch | Ride Hailing Dispatch System | 359.12 | 52 | 993 | 171.5 / 176.6 | `76c60d2cc2e7a6fac25e267fecb9bfccf66a2725934a2e519168082d015da430` |
| audio_09_log_search | Distributed Log Search and Observability Infrastructure | 107.22 | 16 | 307 | 51.6 / 52.4 | `f773e18c613cb5a3984087f729bdfdc67b861efa9c755a19de32cb75d3a5d61d` |
| audio_10_multiregion_db | Multi-Region Database Architecture and Consistency | 123.26 | 19 | 327 | 63.0 / 56.3 | `12dc3faf0830776cba9736a3286e6bc4569c8c23c198bd0faa475e3015125cd1` |

Total: 10 files, 3 219.1 s (53.7 min) of audio, 452 reference segments, 9 025 words.

Reference transcript JSON checksums (sha256): `01` `693d1fb7…`, `02` `cbad8a39…`,
`03` `0d0c937c…`, `04` `5b5a8eff…`, `05` `3ae105e2…`, `06` `0c19899b…`,
`07` `9cd1692f…`, `08` `1793f80e…`, `09` `2a2d7a40…`, `10` `5a219ae7…`;
`all.json` `106157ec…`. Recompute with `shasum -a 256 dataset/*`.

### Reference segment structure (per-file JSON)

Keys: `dataset, audio_id, topic, duration_seconds, speakers, segments[{start,end,speaker,text}]`.
Checked in every file: sorted, no overlaps, no zero-duration segments, no empty
text, **strict speaker alternation** (no two adjacent segments share a speaker),
the gap between segments is exactly 0.300 s, and segments last 2.8–10.4 s (mean ~7 s).

## Deviations from the plan's dataset spec (`PLAN.md` §1, §12)

| Spec | Actual | Status |
|---|---|---|
| 5–6 files | **10 supplied; golden set = 01–06** (`golden_set.json`) | Resolved (Q17). Files 07–10 are retained but not ingested or evaluated |
| 8–10 min each | Golden files are **5.9–7.4 min** (07–08 are 5.8–6.0 min; 09 and 10 are 1.8 and 2.1 min) | Accepted deviation, to be disclosed in `SOLUTION.md` |
| Unique speaker pair per file | Labels are `SPEAKER_00/01` everywhere; voice identity not verifiable from metadata | Open Question Q20 |

## Known defects in the ground truth (verified, originals left untouched)

### D1 — Reference timestamps drift against the audio (all files)

The last segment ends **after** the audio does, by 4.0–4.5 s (files 01–08) and
1.2–1.5 s (files 09, 10). The overrun is **cumulative, at a constant ~0.082 s per
segment boundary**. Method: detect silences with
`ffmpeg -af silencedetect=noise=-40dB:d=0.1`, match each reference inter-segment gap
to the nearest detected silence, and least-squares fit drift against boundary index:

| File | Boundaries | Drift / boundary | Intercept | Mean abs. residual | Max abs. residual |
|---|---|---|---|---|---|
| 01 | 55 | 0.0824 s | −0.029 s | 0.004 s | 0.024 s |
| 02 | 51 | 0.0823 s | −0.024 s | 0.006 s | 0.034 s |
| 03 | 50 | 0.0824 s | −0.029 s | 0.007 s | 0.029 s |
| 04 | 49 | 0.0822 s | −0.026 s | 0.004 s | 0.015 s |
| 05 | 53 | 0.0822 s | −0.026 s | 0.005 s | 0.027 s |
| 06 | 49 | 0.0823 s | −0.024 s | 0.005 s | 0.038 s |
| 07 | 51 | 0.0824 s | −0.027 s | 0.005 s | 0.024 s |
| 08 | 51 | 0.0823 s | −0.029 s | 0.004 s | 0.019 s |
| 09 | 15 | 0.0828 s | −0.031 s | 0.003 s | 0.007 s |
| 10 | 18 | 0.0820 s | −0.024 s | 0.006 s | 0.024 s |

Interpretation: the generator's recorded segment timings are ~82 ms per segment longer
than the audio it actually concatenated. The error is systematic, not noisy, so the
ground truth can be corrected. **Text, speaker labels and segment order are
unaffected.** Uncorrected, this biases DER and any timestamp-based scoring by up to
4.5 s late at the end of a file. **Root cause (established in Session 1):** the per-segment drift is the same at segment
starts and at segment ends (fitted slopes 0.0822–0.0825 s/segment, agreeing to within
0.0001 in every golden file). So the generator's segment **durations are correct** and
only its **inter-segment gap is overstated**: the audio has a ~0.218 s gap where the
JSON says 0.300 s.

**Correction (Q18):** `scripts/correct_reference_timestamps.py` writes
`dataset/reference_corrected/<audio_id>.json` for the golden files (01–06). It applies a
pure shift per segment, `t' = t − b·i`, fitted on speech onsets, so every duration, text
and speaker is preserved. Each output carries a `correction` block with its fit, residuals
and source checksums.

| File | Shift b (s/segment) | Start residual max | End residual max (informational) | Corrected end vs audio end |
|---|---|---|---|---|
| 01 | 0.0824 | 11.9 ms | 47.6 ms | +0.5 ms early |
| 02 | 0.0823 | 16.1 ms | 68.5 ms | 0.7 ms late |
| 03 | 0.0823 | 15.6 ms | 59.9 ms | +1.8 ms early |
| 04 | 0.0822 | 23.5 ms | 24.6 ms | 2.5 ms late |
| 05 | 0.0823 | 13.5 ms | 53.1 ms | 3.9 ms late |
| 06 | 0.0823 | 16.4 ms | 74.0 ms | 2.3 ms late |

End residuals are larger because sentence-final TTS fades cross −40 dB at variable
points, so they measure the detector, not the timing. **Independent check** (raw
signal energy, not silencedetect): energy rises at **307/307** corrected segment starts,
versus 31/307 for the originals. Corrected gaps are uniform at 0.217–0.218 s. Guarded by
`tests/data/test_dataset_integrity.py`.

**Use `dataset/reference_corrected/` for all timestamp-based evaluation (WER alignment,
DER, speaker accuracy, QA ground-truth times).** Files 07–10 are not corrected because
they are outside the golden set.

### D2 — `all.json` QA timestamps come from a different render

`all.json` has 50 QA items, 5 per file. Types: factual 13, reasoning 11, multi_hop 10,
comparative 8, inferential 5, numerical 3. Difficulty: easy 9, medium 19, hard 22.
Each item has `question`, `ground_truth_answer`, `evidence_segment_indices`,
`evidence_time_ranges`, `evidence_speakers` (a **set** of speakers involved, not a
list parallel to the evidence entries), and `supporting_context` (verbatim quotes).

- **`supporting_context` is reliable.** All 134 quotes are verbatim substrings of
  exactly one reference segment (case-insensitive).
- **`evidence_time_ranges` are unusable.** None of the 134 ranges equals any reference
  segment. Each starts 6.8–420.4 s after its quote-matched segment. The large offsets
  come from files 09 and 10. The ranges describe segments of 8.6–18.9 s (mean 12.6 s),
  versus a mean of ~7 s in this audio. They come from a longer render of the
  conversations than the audio supplied.
- **Files 01–08:** `evidence_segment_indices` (0-based) and `evidence_speakers` agree
  with the quote-matched segments in 40/40 items.
- **Files 09, 10:** indices disagree in 9/10 items (for example, index 40 in a
  16-segment file), and `audio_09_log_search__q2` has the wrong speaker set. These two
  audio files are a shortened version of the conversation the QA was written against.
  The quotes still resolve uniquely.

Consequence for Task 6: derive QA ground truth from `supporting_context` → segment
match → (corrected) segment times, and never from `evidence_time_ranges`. See Open
Question Q19.

## How to reproduce these checks

System tools only (`ffprobe`, `ffmpeg`, `jq`, `shasum`). The commands are in
`AGENT_LOG.md` Session 1. They are now automated in
`tests/data/test_dataset_integrity.py` (43 tests, run with `python -m pytest`).
