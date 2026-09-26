"""Golden dataset integrity (Task 1). Guards the ground truth every metric depends on.

Reads committed files only; no ffmpeg, no models, no database. Regenerate the corrected
references with scripts/correct_reference_timestamps.py.
"""
import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest

DATASET = Path(__file__).resolve().parents[2] / "dataset"
CORRECTED = DATASET / "reference_corrected"
MANIFEST = json.loads((DATASET / "golden_set.json").read_text())
FILES = MANIFEST["files"]
IDS = [f["audio_id"] for f in FILES]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def wav_samples(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768, w.getframerate()


def exact_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def assert_well_formed(segments: list[dict]) -> None:
    assert segments, "no segments"
    for i, s in enumerate(segments):
        assert s["end"] > s["start"] >= 0, f"segment {i} has non-positive duration"
        assert s["text"].strip(), f"segment {i} has empty text"
        assert s["speaker"] in {"SPEAKER_00", "SPEAKER_01"}
        if i:
            assert s["start"] >= segments[i - 1]["end"], f"segment {i} overlaps its predecessor"
            assert s["speaker"] != segments[i - 1]["speaker"], f"segment {i}: speakers do not alternate"


def test_golden_set_is_files_01_to_06():
    assert IDS == [
        "audio_01_rate_limiter", "audio_02_url_shortener", "audio_03_chat_system",
        "audio_04_news_feed", "audio_05_payment_idempotency", "audio_06_video_streaming",
    ]


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_audio_checksum_matches_manifest(entry):
    assert hashlib.sha256((DATASET / entry["audio"]).read_bytes()).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_reference_duration_matches_audio(entry):
    ref = load_json(DATASET / entry["reference"])
    assert ref["duration_seconds"] == entry["duration_seconds"]
    # duration_seconds is rounded to 10 ms by the generator
    assert abs(exact_duration(DATASET / entry["audio"]) - ref["duration_seconds"]) < 0.01


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_original_reference_is_well_formed(entry):
    assert_well_formed(load_json(DATASET / entry["reference"])["segments"])


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_corrected_reference_tracks_its_source(entry):
    corrected = load_json(CORRECTED / f"{entry['audio_id']}.json")
    source = DATASET / entry["reference"]
    c = corrected["correction"]
    # Stale if the original changed after correction was run
    assert c["source_reference_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert c["audio_sha256"] == entry["sha256"]
    assert c["start_residual_abs_s"]["max"] <= 0.040
    assert abs(c["start_fit"]["slope_s_per_segment"] - c["end_fit"]["slope_s_per_segment"]) <= 0.001


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_corrected_reference_preserves_content_and_durations(entry):
    orig = load_json(DATASET / entry["reference"])["segments"]
    corr = load_json(CORRECTED / f"{entry['audio_id']}.json")["segments"]
    assert_well_formed(corr)
    assert len(corr) == len(orig)
    for i, (c, o) in enumerate(zip(corr, orig)):
        assert (c["text"], c["speaker"]) == (o["text"], o["speaker"]), f"segment {i} content changed"
        # shift-only correction: each duration survives up to 3-decimal rounding
        assert abs((c["end"] - c["start"]) - (o["end"] - o["start"])) < 0.0015, f"segment {i} duration changed"
    assert corr[-1]["end"] <= exact_duration(DATASET / entry["audio"]) + 0.010


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_corrected_starts_land_on_speech_onsets(entry):
    """Independent of the silencedetect fit: raw signal energy must rise at every start.

    The uncorrected originals pass this at only 2-8 of ~50 boundaries per file.
    """
    x, sr = wav_samples(DATASET / entry["audio"])

    def rms(t0: float, t1: float) -> float:
        return float(np.sqrt(np.mean(x[int(t0 * sr):int(t1 * sr)] ** 2)))

    segments = load_json(CORRECTED / f"{entry['audio_id']}.json")["segments"]
    misses = [i for i, s in enumerate(segments[1:], 1)
              if rms(s["start"] + 0.01, s["start"] + 0.07) <= 4 * rms(s["start"] - 0.06, s["start"] - 0.005)]
    assert not misses, f"segments whose start is not a speech onset: {misses}"


@pytest.mark.parametrize("entry", FILES, ids=IDS)
def test_qa_quotes_resolve_to_exactly_one_segment(entry):
    """all.json evidence_time_ranges are NOT ground truth (defect D2); quotes are."""
    segments = load_json(DATASET / entry["reference"])["segments"]
    items = [q for q in load_json(DATASET / "all.json") if q["audio_id"] == entry["audio_id"]]
    assert len(items) == 5
    for q in items:
        hits = [[i for i, s in enumerate(segments) if quote.lower() in s["text"].lower()]
                for quote in q["supporting_context"]]
        assert all(len(h) == 1 for h in hits), f"{q['qa_id']}: quote matches {hits}"
        assert [h[0] for h in hits] == q["evidence_segment_indices"], f"{q['qa_id']}: indices disagree"
        assert {segments[h[0]]["speaker"] for h in hits} == set(q["evidence_speakers"])
