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
