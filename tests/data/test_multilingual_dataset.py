"""Multilingual evaluation set integrity (Task 17 M8, PLAN.md §7B).

Guards the translated ground truth: every translated file is segment-aligned with its English
source (same count, order and speakers), its QA evidence maps by segment index, and the outputs
are exactly what scripts/build_multilingual_dataset.py produces from the committed translations.
Files marked `synthesized` in the manifest are also checked against their local WAV (exact timing).
"""
import hashlib
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
ML = DATASET / "multilingual"
MANIFEST = json.loads((ML / "manifest.json").read_text(encoding="utf-8"))
FILES = MANIFEST["files"]
LANGS = ["es", "hi", "zh"]
GOLDEN = [f["audio_id"] for f in json.loads((DATASET / "golden_set.json").read_text())["files"]]
SCRIPT = {"hi": re.compile(r"[ऀ-ॿ]"), "zh": re.compile(r"[一-鿿]")}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_covers_every_golden_file_in_every_language():
    assert sorted((f["language"], f["source_audio_id"]) for f in FILES) == sorted(
        (lang, a) for lang in LANGS for a in GOLDEN)


def test_build_is_reproducible_from_committed_translations(tmp_path):
    """Re-running the builder must not change any committed output (no hand edits to generated files)."""
    before = {p: p.read_bytes() for p in ML.rglob("*.json") if "translations" not in p.parts}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_multilingual_dataset.py")], check=True,
                   capture_output=True)
    after = {p: p.read_bytes() for p in ML.rglob("*.json") if "translations" not in p.parts}
    assert after == before


@pytest.mark.parametrize("entry", FILES, ids=[f["audio_id"] for f in FILES])
def test_translation_is_segment_aligned_with_english(entry):
    ref = load(ML / entry["reference"])
    src = load(DATASET / "reference_corrected" / f"{entry['source_audio_id']}.json")
    assert ref["language"] == entry["language"]
    assert len(ref["segments"]) == len(src["segments"]) == entry["segments"]
    for i, (t, s) in enumerate(zip(ref["segments"], src["segments"])):
        assert t["index"] == i
        assert t["speaker"] == s["speaker"], f"segment {i}: speaker changed"
        assert t["text"].strip() and t["text"] != s["text"], f"segment {i}: empty or untranslated"
        if entry["language"] in SCRIPT:
            assert SCRIPT[entry["language"]].search(t["text"]), f"segment {i}: wrong script"
    tr = ref["translation"]
    assert tr["source_reference_sha256"] == hashlib.sha256(
        (DATASET / "reference_corrected" / f"{entry['source_audio_id']}.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("lang", LANGS)
def test_qa_evidence_maps_to_the_same_segments_as_english(lang):
    english = {q["qa_id"]: q for q in load(DATASET / "all.json")}
    qa = load(ML / lang / "qa.json")
    assert len(qa) == 5 * len(GOLDEN)
    for item in qa:
        src = english[item["source_qa_id"]]
        assert item["evidence_segment_indices"] == sorted(set(src["evidence_segment_indices"]))
        assert item["evidence_speakers"] == sorted(src["evidence_speakers"])
        ref = load(ML / lang / f"{item['audio_id']}.json")
        assert item["supporting_context"] == [ref["segments"][i]["text"] for i in item["evidence_segment_indices"]]
        assert item["question"].strip() and item["question"] != src["question"]
        assert item["ground_truth_answer"].strip() and item["ground_truth_answer"] != src["ground_truth_answer"]


SYNTHESIZED = [f for f in FILES if f["status"] == "synthesized"]


def test_status_is_consistent_with_timing():
    for f in FILES:
        ref = load(ML / f["reference"])
        timed = all(s["start"] is not None for s in ref["segments"])
        assert (f["status"] == "synthesized") == timed == (ref["synthesis"] is not None), f["audio_id"]


def test_synthesized_audio_matches_its_reference():
    """Loops rather than parametrizes, so an empty set (nothing synthesised yet) passes instead of skipping."""
    for entry in SYNTHESIZED:
        check_synthesized(entry)


def check_synthesized(entry):
    wav_path = ML / entry["audio"]
    assert wav_path.exists(), f"{wav_path} missing: run scripts/synthesize_multilingual.py"
    assert hashlib.sha256(wav_path.read_bytes()).hexdigest() == entry["sha256"]
    ref = load(ML / entry["reference"])
    with wave.open(str(wav_path)) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 2)
        duration = w.getnframes() / w.getframerate()
    assert abs(duration - ref["duration_seconds"]) <= 0.001
    segs = ref["segments"]
    assert segs[0]["start"] == 0.0 and abs(segs[-1]["end"] - duration) <= 0.001
    gap = ref["synthesis"]["gap_seconds"]
    for a, b in zip(segs, segs[1:]):
        assert b["start"] - a["end"] == pytest.approx(gap, abs=0.002)
        assert b["end"] > b["start"]
