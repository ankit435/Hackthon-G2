"""Primary retrieval criteria (PLAN.md §2, §10.2) against the live index. Run with: pytest -m eval

Thresholds are fixed (Rule 16): a failure here is a finding to diagnose (§10.5), never a number to edit.
"""
import asyncio

import pytest

from api.container import build_evaluation_service
from api.settings import load_settings
from infra.dataset import corrected_references, golden_files, query_set

pytestmark = pytest.mark.eval
RECALL_AT_5, RECALL_AT_10, SPEAKER_ACCURACY, P95_MS = 0.80, 0.90, 0.90, 500.0


@pytest.fixture(scope="module")
def run():
    queries, meta = query_set("en")
    files = golden_files()
    report = asyncio.run(build_evaluation_service(load_settings()).run(
        queries, corrected_references(), {f["audio_id"]: f["sha256"] for f in files}, {f["audio"]: f["audio_id"] for f in files}))
    return report, meta


def test_query_set_is_human_verified(run):
    _, meta = run
    assert meta["verified"] and meta["verified_by"], "query set is LLM-drafted; human verification pending (Task 6)"


@pytest.mark.parametrize("group", ["overall", "keyword", "semantic"])
def test_recall_at_5(run, group):
    assert run[0]["fused"][group]["recall@5"] >= RECALL_AT_5


@pytest.mark.parametrize("group", ["overall", "keyword", "semantic"])
def test_recall_at_10(run, group):
    assert run[0]["fused"][group]["recall@10"] >= RECALL_AT_10


def test_speaker_accuracy_on_top_k(run):
    assert run[0]["speaker_accuracy"]["accuracy"] >= SPEAKER_ACCURACY


def test_search_latency_p95(run):
    assert run[0]["latency_ms"]["p95"] < P95_MS
