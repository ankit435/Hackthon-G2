"""Weighted Reciprocal Rank Fusion (PLAN.md §7). Pure: no I/O, no config, no state. High-risk."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from uuid import UUID

from domain.errors import ConfigurationError
from domain.models import Branch, BranchHit, FusedHit


def _branch(name: Branch | str) -> Branch:
    try:
        return Branch(name)
    except ValueError:
        raise ConfigurationError(f"unknown branch {name!r}", stage="fusion", known=[b.value for b in Branch]) from None


def fuse(ranked: Mapping[Branch | str, Sequence[BranchHit]], k: int,
         weights: Mapping[Branch | str, float]) -> list[FusedHit]:
    """fused(c) = sum over branches b whose list contains c of weights[b] / (k + rank_b(c)). Sorted best first.

    Contract and edge-case decisions:
    - rank_b(c) is c's 1-based position in branch b's list, scoped to that branch. A hit whose
      `.rank` disagrees with its position raises ValueError, so a 0-based producer cannot sneak in.
    - The weight multiplies each branch's term BEFORE summing. Weighting the sum would scale
      every chunk identically and change nothing (the silent no-op bug).
    - A chunk absent from a branch gets nothing from it: no penalty, no zero-fill.
    - Weight 0.0 is legal and disables the branch entirely: its hits are not fused at all, so they
      cannot pad the result with zero-score entries. (The WARNING is logged when settings load.)
    - A branch missing from `weights` gets 1.0. An unknown branch name in either mapping, a
      negative or non-finite weight, or k <= 0 raises ConfigurationError.
    - The same chunk twice in one branch raises ValueError (it would be counted twice).
    - Ties: fused score descending, then best (lowest) single-branch rank, then chunk id as a
      string. Arbitrary but deterministic, so the evaluated path is reproducible (Rule 8).
    - Empty input or all-empty branches -> [].
    The caller slices to top-K AFTER this; slicing branches first would discard cross-branch agreement.
    """
    if not isinstance(k, int) or k <= 0:
        raise ConfigurationError("RRF k must be a positive integer", stage="fusion", k=k)
    resolved = {_branch(b): float(w) for b, w in weights.items()}
    for b, w in resolved.items():
        if not math.isfinite(w) or w < 0:
            raise ConfigurationError("fusion weight must be finite and >= 0", stage="fusion", branch=b.value, weight=w)

    scores: dict[UUID, float] = {}
    best_rank: dict[UUID, int] = {}
    for name, hits in ranked.items():
        branch = _branch(name)
        weight = resolved.get(branch, 1.0)
        if weight == 0.0:
            continue
        seen: set[UUID] = set()
        for position, hit in enumerate(hits, start=1):
            if hit.rank != position:
                raise ValueError(f"{branch.value}: hit at position {position} carries rank {hit.rank}")
            if hit.chunk_id in seen:
                raise ValueError(f"{branch.value}: chunk {hit.chunk_id} appears twice")
            seen.add(hit.chunk_id)
            contribution = weight / (k + position)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + contribution
            best_rank[hit.chunk_id] = min(best_rank.get(hit.chunk_id, position), position)

    ordered = sorted(scores, key=lambda cid: (-scores[cid], best_rank[cid], str(cid)))
    return [FusedHit(chunk_id=cid, score=scores[cid]) for cid in ordered]
