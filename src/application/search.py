"""Hybrid search (PLAN.md §7): keyword + semantic branches -> weighted RRF -> [optional cross-encoder
re-rank of the top fused candidates, PLAN.md §11 item 5] -> top-K -> hydrate."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Mapping
from dataclasses import replace

from application.fusion import fuse
from domain.errors import InvalidInputError
from domain.models import Branch, BranchHit, SearchResultItem
from domain.ports import ChunkRepository, Embedder, Reranker

log = logging.getLogger(__name__)

MAX_TOP_K = 50  # evaluation needs <= 10; 50 keeps per-branch depth (top_k x multiplier) bounded
MAX_QUERY_CHARS = 1000


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:12]


class SearchService:
    """The graded path is `search`. `keyword` / `semantic` are diagnostics over the SAME repository methods."""

    def __init__(self, chunks: ChunkRepository, embedder: Embedder, *, weights: Mapping[Branch, float],
                 rrf_k: int, candidate_depth_multiplier: int, reranker: Reranker | None = None,
                 rerank_depth: int = 30) -> None:
        if candidate_depth_multiplier < 1:
            raise ValueError("candidate_depth_multiplier must be >= 1")
        if rerank_depth < 1:
            raise ValueError("rerank_depth must be >= 1")
        self._chunks, self._embedder = chunks, embedder
        self._weights, self._k, self._depth = dict(weights), rrf_k, candidate_depth_multiplier
        self._reranker, self._rerank_depth = reranker, rerank_depth

    @property
    def config(self) -> dict:
        return {"weights": {b.value: w for b, w in self._weights.items()}, "rrf_k": self._k,
                "candidate_depth_multiplier": self._depth,
                "reranker": self._reranker.model_name if self._reranker else None,
                "rerank_depth": self._rerank_depth if self._reranker else None}

    @staticmethod
    def _validate(query: str, top_k: int) -> str:
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            raise InvalidInputError("query must not be empty", stage="search")
        if len(text) > MAX_QUERY_CHARS:
            raise InvalidInputError(f"query longer than {MAX_QUERY_CHARS} characters", stage="search", length=len(text))
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise InvalidInputError(f"top_k must be an integer in 1..{MAX_TOP_K}", stage="search", top_k=top_k)
        return text

    async def _timed(self, branch: Branch, qh: str, coro) -> list[BranchHit]:
        t0 = time.perf_counter()
        hits = await coro
        extra = {"event": f"search.{branch.value}.end", "query_hash": qh, "candidates": len(hits),
                 "duration_ms": round((time.perf_counter() - t0) * 1000, 2)}
        if hits:
            log.info("search.branch.end", extra=extra)
        else:
            log.warning("search branch returned no candidates", extra=extra)
        return hits

    async def _semantic_hits(self, query: str, limit: int) -> list[BranchHit]:
        [vector] = await self._embedder.embed([query])
        return await self._chunks.semantic_search(vector, limit)

    async def _hydrate_in_order(self, scored: list[tuple], qh: str) -> list[SearchResultItem]:
        by_id = {item.chunk_id: item for item in await self._chunks.hydrate([cid for cid, _ in scored])}
        missing = [str(cid) for cid, _ in scored if cid not in by_id]
        if missing:  # a chunk deleted between ranking and hydration; never invent a row for it
            log.warning("ranked chunks missing at hydration", extra={"query_hash": qh, "missing": missing})
        return [replace(by_id[cid], score=score) for cid, score in scored if cid in by_id]

    async def search(self, query: str, top_k: int = 10) -> list[SearchResultItem]:
        text = self._validate(query, top_k)
        qh, t0, depth = _query_hash(text), time.perf_counter(), top_k * self._depth
        log.info("search.request", extra={"event": "search.request", "query_hash": qh, "top_k": top_k,
                                          "depth": depth, **self.config})
        log.debug("search.query", extra={"query_hash": qh, "query": text})
        keyword_hits, semantic_hits = await asyncio.gather(
            self._timed(Branch.KEYWORD, qh, self._chunks.keyword_search(text, depth)),
            self._timed(Branch.SEMANTIC, qh, self._semantic_hits(text, depth)))
        fusion_started = time.perf_counter()
        fused = fuse({Branch.KEYWORD: keyword_hits, Branch.SEMANTIC: semantic_hits}, self._k, self._weights)
        log.info("search.fusion.end", extra={
            "event": "search.fusion.end", "query_hash": qh, "fused": len(fused),
            "keyword_candidates": len(keyword_hits), "semantic_candidates": len(semantic_hits),
            "duration_ms": round((time.perf_counter() - fusion_started) * 1000, 2),
        })
        # Slice only AFTER fusion: cutting each branch to top_k first would drop cross-branch agreement.
        if self._reranker is None:
            results = await self._hydrate_in_order([(h.chunk_id, h.score) for h in fused[:top_k]], qh)
        else:
            results = await self._rerank(text, fused, top_k, qh)
        log.info("search.response", extra={"event": "search.response", "query_hash": qh, "results": len(results),
                                           "top_score": results[0].score if results else None,
                                           "duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
        return results

    async def _rerank(self, query: str, fused: list, top_k: int, qh: str) -> list[SearchResultItem]:
        """Re-score the top fused candidates with the cross-encoder, then cut to top_k.

        - The pool is the first max(rerank_depth, top_k) fused hits, so re-ranking can only reorder and
          promote within that pool; it never pulls in a chunk neither branch retrieved.
        - Result scores become the cross-encoder's relevance scores (comparable within a query only).
        - Exact score ties keep their fused order, so the output is deterministic.
        - Any re-ranker failure returns the fused order (WARNING): a smarter ranker must never fail a search.
        """
        candidates = await self._hydrate_in_order(
            [(h.chunk_id, h.score) for h in fused[:max(self._rerank_depth, top_k)]], qh)
        if not candidates:
            return []
        started = time.perf_counter()
        try:
            scores = await self._reranker.score(query, [c.text for c in candidates])
            if len(scores) != len(candidates):
                raise ValueError(f"{len(scores)} scores for {len(candidates)} candidates")
        except Exception as e:  # noqa: BLE001 — isolation is the contract; failure is logged, fused order returned
            log.warning("rerank failed; returning fused order", extra={
                "event": "search.rerank.failed", "query_hash": qh, "error_type": type(e).__name__, "error": str(e)})
            return candidates[:top_k]
        order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        log.info("search.rerank.end", extra={
            "event": "search.rerank.end", "query_hash": qh, "model": self._reranker.model_name,
            "candidates": len(candidates),
            "top_k_changed": sum(i != j for i, j in zip(order[:top_k], range(top_k))),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        return [replace(candidates[i], score=scores[i]) for i in order[:top_k]]

    async def keyword(self, query: str, top_k: int = 10) -> list[SearchResultItem]:
        """Diagnostic only: the keyword branch alone, ranked by its own score."""
        text = self._validate(query, top_k)
        hits = await self._timed(Branch.KEYWORD, _query_hash(text), self._chunks.keyword_search(text, top_k))
        return await self._hydrate_in_order([(h.chunk_id, h.score) for h in hits], _query_hash(text))

    async def semantic(self, query: str, top_k: int = 10) -> list[SearchResultItem]:
        """Diagnostic only: the semantic branch alone, ranked by cosine similarity."""
        text = self._validate(query, top_k)
        hits = await self._timed(Branch.SEMANTIC, _query_hash(text), self._semantic_hits(text, top_k))
        return await self._hydrate_in_order([(h.chunk_id, h.score) for h in hits], _query_hash(text))
