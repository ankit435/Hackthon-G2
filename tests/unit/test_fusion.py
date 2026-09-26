import math
from uuid import UUID

import pytest

from application.fusion import fuse
from domain.errors import ConfigurationError
from domain.models import Branch, BranchHit

KW, SEM = Branch.KEYWORD, Branch.SEMANTIC
A, B, C, D = (UUID(int=i) for i in (1, 2, 3, 4))


def hits(*ids):
    return [BranchHit(chunk_id=c, rank=i, score=0.0) for i, c in enumerate(ids, start=1)]


def as_dict(fused):
    return {h.chunk_id: h.score for h in fused}


def test_hand_computed_example():
    # k=60, weights kw=2.0 sem=1.0
    # A: kw rank 1 -> 2/61 ; sem rank 3 -> 1/63
    # B: kw rank 2 -> 2/62 ; absent in sem
    # C: absent in kw      ; sem rank 1 -> 1/61
    # D: sem rank 2 -> 1/62
    fused = fuse({KW: hits(A, B), SEM: hits(C, D, A)}, k=60, weights={KW: 2.0, SEM: 1.0})
    expected = {A: 2 / 61 + 1 / 63, B: 2 / 62, C: 1 / 61, D: 1 / 62}
    assert as_dict(fused) == pytest.approx(expected)
    assert [h.chunk_id for h in fused] == [A, B, C, D]  # 0.04866, 0.03226, 0.01639, 0.01613


def test_rank_is_one_based_and_per_branch():
    # A is 3rd in keyword and 7th in semantic: two separate terms, 1/(60+3) + 1/(60+7)
    kw = hits(B, C, A)
    sem = hits(*(UUID(int=100 + i) for i in range(6)), A)
    assert as_dict(fuse({KW: kw, SEM: sem}, 60, {}))[A] == pytest.approx(1 / 63 + 1 / 67)


def test_single_top_hit_scores_one_over_k_plus_one():
    assert as_dict(fuse({KW: hits(A)}, 60, {}))[A] == pytest.approx(1 / 61)  # 0-based would give 1/60


def test_weight_multiplies_per_branch_term_not_the_sum():
    """Weighting the sum would scale A and B identically and leave the order unchanged."""
    ranked = {KW: hits(A, B), SEM: hits(B, A)}
    # Equal weights: A and B tie exactly; tie-break (best rank 1 both) -> id order -> A first
    equal = fuse(ranked, 60, {KW: 1.0, SEM: 1.0})
    assert as_dict(equal)[A] == pytest.approx(as_dict(equal)[B])
    # Upweight semantic: B (1st in semantic) must now beat A. Post-sum weighting cannot do this.
    weighted = fuse(ranked, 60, {KW: 1.0, SEM: 3.0})
    assert [h.chunk_id for h in weighted] == [B, A]
    assert as_dict(weighted)[B] == pytest.approx(1 / 62 + 3 / 61)


def test_absence_contributes_nothing():
    fused = as_dict(fuse({KW: hits(A), SEM: hits(B)}, 60, {}))
    assert fused == pytest.approx({A: 1 / 61, B: 1 / 61})  # no penalty, no zero-fill term


def test_cross_branch_agreement_beats_a_single_top_rank():
    # C is only 5th in each branch but in both; A is 1st in keyword only.
    kw = hits(A, *(UUID(int=200 + i) for i in range(3)), C)
    sem = hits(*(UUID(int=300 + i) for i in range(4)), C)
    fused = fuse({KW: kw, SEM: sem}, 60, {})
    assert fused[0].chunk_id == C and fused[0].score == pytest.approx(2 / 65) and 2 / 65 > 1 / 61


def test_branch_missing_from_weights_gets_one():
    assert as_dict(fuse({KW: hits(A)}, 60, {SEM: 5.0}))[A] == pytest.approx(1 / 61)


def test_zero_weight_disables_the_branch_entirely():
    fused = fuse({KW: hits(A), SEM: hits(B)}, 60, {SEM: 0.0})
    assert [h.chunk_id for h in fused] == [A]


@pytest.mark.parametrize("weight", [-0.5, math.nan, math.inf])
def test_invalid_weight_is_a_configuration_error(weight):
    with pytest.raises(ConfigurationError):
        fuse({KW: hits(A)}, 60, {KW: weight})


@pytest.mark.parametrize("where", ["ranked", "weights"])
def test_unknown_branch_name_fails_loudly(where):
    ranked, weights = {KW: hits(A)}, {}
    if where == "ranked":
        ranked["bm25"] = hits(B)
    else:
        weights["bm25"] = 1.0
    with pytest.raises(ConfigurationError, match="unknown branch 'bm25'"):
        fuse(ranked, 60, weights)


def test_string_branch_names_are_accepted():
    assert as_dict(fuse({"keyword": hits(A)}, 60, {"keyword": 2.0}))[A] == pytest.approx(2 / 61)


@pytest.mark.parametrize("k", [0, -1, 1.5])
def test_invalid_k_is_rejected(k):
    with pytest.raises(ConfigurationError):
        fuse({KW: hits(A)}, k, {})


def test_zero_based_ranks_are_rejected():
    with pytest.raises(ValueError, match="position 1 carries rank 0"):
        fuse({KW: [BranchHit(A, 0, 0.0)]}, 60, {})


def test_duplicate_chunk_within_a_branch_is_rejected():
    with pytest.raises(ValueError, match="twice"):
        fuse({KW: [BranchHit(A, 1, 0.0), BranchHit(A, 2, 0.0)]}, 60, {})


def test_empty_inputs():
    assert fuse({}, 60, {}) == []
    assert fuse({KW: [], SEM: []}, 60, {}) == []


def test_exact_score_tie_prefers_the_better_single_rank_over_id_order():
    # k=1 keeps the floats exact: X = kw rank 1 -> 1/2 ; Y = kw rank 3 + sem rank 3 -> 1/4 + 1/4 = 1/2
    x, y = UUID(int=9), UUID(int=1)  # id order alone would put Y first
    f1, f2, f3 = UUID(int=50), UUID(int=51), UUID(int=52)  # distinct fillers so only X and Y share a score
    fused = fuse({KW: hits(x, f1, y), SEM: hits(f2, f3, y)}, 1, {})
    assert as_dict(fused)[x] == as_dict(fused)[y] == 0.5
    order = [h.chunk_id for h in fused]
    assert order.index(x) < order.index(y)


def test_ties_break_by_best_rank_then_id():
    # A: kw 1 + sem 3 ; B: kw 3 + sem 1  -> equal sums, equal best rank -> id order
    # D: kw 2 + sem 2 -> 2/62 = 0.032258 vs 1/61+1/63 = 0.032266 -> D slightly lower
    fused = fuse({KW: hits(A, D, B), SEM: hits(B, D, A)}, 60, {})
    assert [h.chunk_id for h in fused] == [A, B, D]
    reordered = fuse({SEM: hits(B, D, A), KW: hits(A, D, B)}, 60, {})
    assert fused == reordered  # input mapping order never changes the output
