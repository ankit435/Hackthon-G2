"""Reads the committed golden dataset and labeled query sets (file I/O stays in infra)."""
import json
from pathlib import Path

from domain.models import LabeledQuery, RefSegment

DATASET = Path(__file__).resolve().parents[2] / "dataset"


def golden_files() -> list[dict]:
    return json.loads((DATASET / "golden_set.json").read_text())["files"]


def corrected_references() -> dict[str, list[RefSegment]]:
    """Drift-corrected reference segments (defect D1): never the uncorrected originals."""
    return {f["audio_id"]: [RefSegment(i, s["start"], s["end"], s["speaker"]) for i, s in enumerate(
                json.loads((DATASET / "reference_corrected" / f"{f['audio_id']}.json").read_text())["segments"])]
            for f in golden_files()}


def query_set(language: str = "en") -> tuple[list[LabeledQuery], dict]:
    data = json.loads((DATASET / "queries" / f"{language}.json").read_text())
    queries = [LabeledQuery(q["id"], q["text"], q["kind"], tuple((a, i) for a, i in q["evidence"])) for q in data["queries"]]
    return queries, {k: v for k, v in data.items() if k != "queries"}


def multilingual_manifest() -> dict:
    return json.loads((DATASET / "multilingual" / "manifest.json").read_text())


def multilingual_files(language: str) -> list[dict]:
    """Manifest entries for one language (Task 17 M8). Each carries audio path, reference path, sha256."""
    return [f for f in multilingual_manifest()["files"] if f["language"] == language]


def multilingual_references(language: str) -> dict[str, list[RefSegment]]:
    """Reference segments from the synthesis itself (exact timings, no D1-style drift to correct)."""
    refs = {}
    for f in multilingual_files(language):
        segments = json.loads((DATASET / "multilingual" / f["reference"]).read_text())["segments"]
        refs[f["audio_id"]] = [RefSegment(s["index"], s["start"], s["end"], s["speaker"]) for s in segments]
    return refs


def multilingual_query_set(language: str) -> list[LabeledQuery]:
    """QA ground truth translated 1:1 by segment index (Task 17 M8). All items are semantic-style questions."""
    qa = json.loads((DATASET / "multilingual" / language / "qa.json").read_text())
    return [LabeledQuery(q["qa_id"], q["question"], "semantic",
                         tuple((q["audio_id"], i) for i in q["evidence_segment_indices"])) for q in qa]
