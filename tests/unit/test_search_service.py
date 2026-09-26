"""SearchService with fakes: no database, no model."""
import asyncio
import logging
from uuid import UUID

import pytest

from application.search import MAX_TOP_K, SearchService
from domain.errors import InvalidInputError
from domain.models import Branch, BranchHit, SearchResultItem

ids = {name: UUID(int=i) for i, name in enumerate("ABCDEFGHIJ", start=1)}


def hits(*names):
    return [BranchHit(ids[n], rank, 1.0 / rank) for rank, n in enumerate(names, start=1)]


class FakeRepo:
    def __init__(self, keyword, semantic):
        self._kw, self._sem, self.calls = keyword, semantic, []

    async def keyword_search(self, query, limit):
        self.calls.append(("keyword", query, limit))
        return self._kw[:limit]

    async def semantic_search(self, vector, limit):
        self.calls.append(("semantic", tuple(vector), limit))
        return self._sem[:limit]

    async def hydrate(self, chunk_ids):
        self.calls.append(("hydrate", list(chunk_ids)))
        name = {v: k for k, v in ids.items()}
        return [SearchResultItem(chunk_id=cid, audio_file_id=UUID(int=0), file_name=f"{name[cid]}.wav",
                                 file_path=f"/{name[cid]}.wav", speaker="SPEAKER_00", start_time=0.0, end_time=1.0,
                                 text=name[cid], language="en", score=0.0) for cid in reversed(chunk_ids)]  # order scrambled on purpose


class FakeEmbedder:
    dimension, max_tokens = 2, 256

    def __init__(self):
        self.calls = []

    def count_tokens(self, text):
        return 1

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.5, 0.5] for _ in texts]


def service(repo, weights=None, k=60, depth=5, embedder=None):
    return SearchService(repo, embedder or FakeEmbedder(), weights=weights or {Branch.KEYWORD: 1.0, Branch.SEMANTIC: 1.0},
                         rrf_k=k, candidate_depth_multiplier=depth)


def names(results):
    return [r.text for r in results]


def test_slices_to_top_k_only_after_fusion():
    # C is 4th in both branches; A is 1st in keyword only, B 1st in semantic only.
    # top_k=1 slicing each branch FIRST would never even see C. Fused: C = 2/64 = 0.03125 > 1/61 = 0.01639
    repo = FakeRepo(hits("A", "D", "E", "C"), hits("B", "F", "G", "C"))
    results = asyncio.run(service(repo).search("q", top_k=1))
    assert names(results) == ["C"] and results[0].score == pytest.approx(2 / 64)
    assert ("keyword", "q", 5) in repo.calls and ("semantic", (0.5, 0.5), 5) in repo.calls  # depth = 1 x 5


def test_hydrates_only_the_top_k_ids_and_preserves_fused_order():
    repo = FakeRepo(hits("A", "B", "C", "D"), hits("A", "C", "B"))
    results = asyncio.run(service(repo).search("q", top_k=3))
    # A: 2/61. B: 1/62+1/63 and C: 1/63+1/62 tie exactly; best rank 2 both -> id order -> B then C. D (1/64) is cut.
    assert names(results) == ["A", "B", "C"]
    [hydrate_call] = [c for c in repo.calls if c[0] == "hydrate"]
    assert hydrate_call[1] == [ids["A"], ids["B"], ids["C"]]  # only the top_k ids, in fused order
    assert all(r.score > 0 for r in results)


def test_configured_weights_reach_fusion():
    repo = FakeRepo(hits("A"), hits("B"))
    assert names(asyncio.run(service(repo, weights={Branch.KEYWORD: 1.0, Branch.SEMANTIC: 2.0}).search("q", 2))) == ["B", "A"]
    assert names(asyncio.run(service(repo, weights={Branch.KEYWORD: 2.0, Branch.SEMANTIC: 1.0}).search("q", 2))) == ["A", "B"]


def test_rrf_k_reaches_fusion():
    repo = FakeRepo(hits("A"), [])
    assert asyncio.run(service(repo, k=10).search("q", 1))[0].score == pytest.approx(1 / 11)


def test_query_is_embedded_once_per_search():
    embedder = FakeEmbedder()
    asyncio.run(service(FakeRepo(hits("A"), hits("A")), embedder=embedder).search("  hello  ", 5))
    assert embedder.calls == [["hello"]]


def test_diagnostic_branches_reuse_the_same_repository_methods():
    repo = FakeRepo(hits("A", "B"), hits("C"))
    svc = service(repo)
    assert names(asyncio.run(svc.keyword("q", 2))) == ["A", "B"]
    assert names(asyncio.run(svc.semantic("q", 2))) == ["C"]
    methods = [c[0] for c in repo.calls]
    assert methods == ["keyword", "hydrate", "semantic", "hydrate"]
    assert ("keyword", "q", 2) in repo.calls  # diagnostics fetch top_k, not the fused depth


def test_diagnostic_results_carry_branch_scores():
    results = asyncio.run(service(FakeRepo(hits("A", "B"), [])).keyword("q", 2))
    assert [r.score for r in results] == [1.0, 0.5]


def test_one_empty_branch_still_returns_the_other_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="application.search"):
        results = asyncio.run(service(FakeRepo([], hits("B", "A"))).search("q", 2))
    assert names(results) == ["B", "A"]
    assert any(getattr(r, "event", "") == "search.keyword.end" for r in caplog.records)


def test_no_matches_anywhere_returns_empty():
    assert asyncio.run(service(FakeRepo([], [])).search("q", 5)) == []


def test_request_log_carries_active_weights_and_k(caplog):
    with caplog.at_level(logging.INFO, logger="application.search"):
        asyncio.run(service(FakeRepo(hits("A"), hits("A")), weights={Branch.KEYWORD: 1.0, Branch.SEMANTIC: 0.5}).search("q", 1))
    [req] = [r for r in caplog.records if getattr(r, "event", "") == "search.request"]
    assert req.weights == {"keyword": 1.0, "semantic": 0.5} and req.rrf_k == 60 and req.top_k == 1
    assert len(req.query_hash) == 12 and not hasattr(req, "query")  # raw query only at DEBUG
    [resp] = [r for r in caplog.records if getattr(r, "event", "") == "search.response"]
    assert resp.results == 1 and resp.top_score == pytest.approx(1 / 61 + 0.5 / 61)


@pytest.mark.parametrize("query", ["", "   ", None, "x" * 1001])
def test_invalid_query_is_rejected(query):
    with pytest.raises(InvalidInputError):
        asyncio.run(service(FakeRepo([], [])).search(query, 5))


@pytest.mark.parametrize("top_k", [0, -1, MAX_TOP_K + 1, 2.5, True, "5"])
def test_invalid_top_k_is_rejected(top_k):
    with pytest.raises(InvalidInputError):
        asyncio.run(service(FakeRepo([], [])).search("q", top_k))


def test_hydration_gap_is_dropped_not_invented(caplog):
    class Gappy(FakeRepo):
        async def hydrate(self, chunk_ids):
            return [r for r in await super().hydrate(chunk_ids) if r.chunk_id != ids["A"]]

    with caplog.at_level(logging.WARNING):
        results = asyncio.run(service(Gappy(hits("A", "B"), [])).search("q", 2))
    assert names(results) == ["B"] and any("missing at hydration" in r.message for r in caplog.records)
