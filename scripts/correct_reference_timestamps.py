"""Derive drift-corrected reference transcripts for the golden set (defect D1, PROGRESS.md Q18).

The generator's reference timestamps run late by ~82 ms per segment boundary, so a
file's final segments are misplaced by several seconds. Originals are never modified;
this writes dataset/reference_corrected/<audio_id>.json.

Method, per file:
  1. ffmpeg silencedetect finds pauses in the audio.
  2. Each reference boundary (end of segment i-1 -> start of segment i) is matched to
     the detected pause nearest its drift-adjusted position. Drift is tracked
     sequentially from boundary to boundary, so no drift rate is assumed up front.
  3. Starts and ends are fitted SEPARATELY as linear functions of segment index:
       ref_start_i - speech_onset_i  = a_s + b_s * i
       ref_end_i   - speech_offset_i = a_e + b_e * i
  4. Measured on this dataset (Session 1): b_s == b_e (~0.0824 s). Drift accumulates
     equally at both ends of every segment, so the generator's segment DURATIONS are
     right and only its inter-segment GAPS were overstated. The correction is therefore
     a pure per-segment shift, t' = t - b_s * i, which keeps every reference duration
     intact. b_s comes from the starts: speech onsets are sharp (residual sd ~5 ms),
     while offsets are sentence-final fades whose -40 dB crossing varies (sd 10-19 ms).
     The intercepts (~-0.01 s start, ~+0.03 s end) are silencedetect threshold bias,
     not generator error, and are recorded but not applied.

Refuses to write a file if start residuals exceed MAX_RESIDUAL_S, if the start and end
slopes disagree (the shift model would be wrong), or if corrected segments overlap or
run past the audio. A bad fit must fail loudly, never ship.

Run from the repo root inside the venv:  python scripts/correct_reference_timestamps.py
"""
import hashlib
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
OUT_DIR = DATASET / "reference_corrected"
SILENCE_NOISE_DB = -40
SILENCE_MIN_S = 0.1
MAX_RESIDUAL_S = 0.040
MAX_SLOPE_DISAGREEMENT = 0.001  # s/segment; ~0.1 s over a 50-segment file
# The generator ends the last segment exactly at the last audio sample (tail ~0), so the
# corrected end lands within fit precision of the file end (slope uncertainty x ~50
# segments ~ a few ms). 10 ms = the resolution of the generator's own duration_seconds.
END_BOUND_TOLERANCE_S = 0.010
MAX_MATCH_DISTANCE_S = 0.25  # a boundary further than this from any pause is unmatched


def detect_silences(wav: Path) -> list[tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    if len(starts) != len(ends):
        raise RuntimeError(f"{wav.name}: unpaired silencedetect output ({len(starts)} starts, {len(ends)} ends)")
    return list(zip(starts, ends))


def match_boundaries(segments: list[dict], silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return (speech_offset_of_prev, speech_onset_of_next) for every boundary 1..n-1.

    Drift accumulates, so each boundary is searched around its reference midpoint minus
    the drift observed at the previous boundary. Every boundary must match a distinct
    pause, in order; anything else is an error, never a skip.
    """
    matched, drift, last_k = [], 0.0, -1
    for i in range(1, len(segments)):
        ref_mid = (segments[i - 1]["end"] + segments[i]["start"]) / 2
        expected = ref_mid - drift
        k = min(range(len(silences)), key=lambda j: abs((silences[j][0] + silences[j][1]) / 2 - expected))
        pause_mid = (silences[k][0] + silences[k][1]) / 2
        if abs(pause_mid - expected) > MAX_MATCH_DISTANCE_S or k <= last_k:
            raise RuntimeError(f"boundary {i}: no distinct pause near {expected:.3f}s (nearest {pause_mid:.3f}s)")
        matched.append(silences[k])
        drift, last_k = ref_mid - pause_mid, k
    return matched


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def residuals(xs, ys, a, b):
    return [y - (a + b * x) for x, y in zip(xs, ys)]


def exact_duration(wav: Path) -> float:
    # The JSON duration_seconds is rounded to 10 ms; bounds checks need the sample-exact length.
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def correct_file(entry: dict) -> dict:
    ref_path = DATASET / entry["reference"]
    ref = json.loads(ref_path.read_text())
    segs, duration = ref["segments"], exact_duration(DATASET / entry["audio"])
    pauses = match_boundaries(segs, detect_silences(DATASET / entry["audio"]))

    # Boundary i (1-based) = pause between segment i-1 and i: its start is where
    # segment i-1's speech ends and its end is where segment i's speech starts.
    start_idx = list(range(1, len(segs)))
    start_off = [segs[i]["start"] - pauses[i - 1][1] for i in start_idx]
    end_idx = list(range(0, len(segs) - 1))
    end_off = [segs[i]["end"] - pauses[i][0] for i in end_idx]

    a_s, b_s = linear_fit(start_idx, start_off)
    a_e, b_e = linear_fit(end_idx, end_off)
    start_res = [abs(r) for r in residuals(start_idx, start_off, a_s, b_s)]
    end_res = [abs(r) for r in residuals(end_idx, end_off, a_e, b_e)]

    # Same shift for start and end: durations are preserved (see module docstring, step 4).
    corrected = [
        {**s, "start": round(s["start"] - b_s * i, 3), "end": round(s["end"] - b_s * i, 3)}
        for i, s in enumerate(segs)
    ]

    problems = []
    if max(start_res) > MAX_RESIDUAL_S:
        problems.append(f"max start residual {max(start_res):.3f}s > {MAX_RESIDUAL_S}s")
    if abs(b_s - b_e) > MAX_SLOPE_DISAGREEMENT:
        problems.append(f"start slope {b_s:.4f} != end slope {b_e:.4f}: segment durations are not preserved, the shift model does not hold")
    if corrected[-1]["end"] > duration + END_BOUND_TOLERANCE_S:
        problems.append(f"last end {corrected[-1]['end']}s > duration {duration}s")
    for i, s in enumerate(corrected):
        if s["end"] <= s["start"] or (i and s["start"] < corrected[i - 1]["end"]):
            problems.append(f"segment {i} invalid or overlapping: {s['start']}-{s['end']}")
    if problems:
        raise RuntimeError(f"{entry['audio_id']}: " + "; ".join(problems))

    return {
        **ref,
        "segments": corrected,
        "correction": {
            "defect": "D1 (dataset/PROVENANCE.md)",
            "source_reference": entry["reference"],
            "source_reference_sha256": sha256(ref_path),
            "audio_sha256": entry["sha256"],
            "method": "t' = t - b*i per segment i; b = slope of (reference start - detected speech onset) vs i. Durations preserved; intercepts are detector bias and not applied",
            "shift_s_per_segment": round(b_s, 5),
            "silencedetect": {"noise_db": SILENCE_NOISE_DB, "min_duration_s": SILENCE_MIN_S},
            "start_fit": {"intercept_s": round(a_s, 5), "slope_s_per_segment": round(b_s, 5)},
            "end_fit": {"intercept_s": round(a_e, 5), "slope_s_per_segment": round(b_e, 5)},
            "boundaries_matched": len(pauses),
            "start_residual_abs_s": {"mean": round(sum(start_res) / len(start_res), 4), "max": round(max(start_res), 4)},
            "end_residual_abs_s_informational": {"mean": round(sum(end_res) / len(end_res), 4), "max": round(max(end_res), 4)},
            "audio_duration_exact_s": round(duration, 4),
            "last_end_s": corrected[-1]["end"],
            "tail_s": round(duration - corrected[-1]["end"], 4),  # may be slightly negative, within END_BOUND_TOLERANCE_S
        },
    }


def main() -> int:
    manifest = json.loads((DATASET / "golden_set.json").read_text())
    OUT_DIR.mkdir(exist_ok=True)
    for entry in manifest["files"]:
        result = correct_file(entry)
        (OUT_DIR / f"{entry['audio_id']}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        c = result["correction"]
        print(f"{entry['audio_id']:<30} start b={c['start_fit']['slope_s_per_segment']:.4f} a={c['start_fit']['intercept_s']:+.3f} | "
              f"end b={c['end_fit']['slope_s_per_segment']:.4f} a={c['end_fit']['intercept_s']:+.3f} | "
              f"start resid max={c['start_residual_abs_s']['max']:.4f} | end resid max={c['end_residual_abs_s_informational']['max']:.4f} | tail={c['tail_s']*1000:+.1f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
