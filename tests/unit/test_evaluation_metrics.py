"""Metric core against hand-computed examples (PLAN.md §10: verify before trusting any number)."""
import pytest

from application.evaluation import (
    covers,
    score_query,
    speaker_correct,
    speaker_mapping,
    summarize,
)
from domain.models import Hit, LabeledQuery, RefSegment

# File "f": four reference segments, alternating speakers A/B.
REFS = {
    "f": [RefSegment(0, 0.0, 10.0, "A"), RefSegment(1, 10.2, 20.0, "B"), RefSegment(2, 20.2, 30.0, "A"),
          RefSegment(3, 30.2, 40.0, "B")],
    "g": [RefSegment(0, 0.0, 10.0, "A")],
}


def H(start, end, file="f", speaker="S0"):
    return Hit(file, start, end, speaker)


# ---- covers ------------------------------------------------------------------------------

def test_cover_uses_the_shorter_span():
    seg = REFS["f"][1]  # 10.2-20.0 (9.8 s)
    assert covers(H(10.2, 20.0), "f", seg)            # identical
    assert covers(H(12.0, 14.0), "f", seg)            # short chunk fully inside the segment
    assert covers(H(5.0, 25.0), "f", seg)             # long chunk containing the segment
    assert covers(H(14.0, 25.0), "f", seg)            # overlap 6.0 >= 0.5 * 9.8 = 4.9
    assert not covers(H(16.0, 25.0), "f", seg)        # overlap 4.0 < 4.9
    assert not covers(H(19.8, 20.4), "f", seg)        # grazing: overlap 0.2 vs shorter 0.6 -> 0.33 < 0.5


def test_cover_requires_the_same_file_and_positive_length():
    assert not covers(H(10.2, 20.0, file="g"), "f", REFS["f"][1])
    assert not covers(H(12.0, 12.0), "f", REFS["f"][1])


# ---- score_query: hand-computed -------------------------------------------------------------

def test_hand_computed_recall_hit_and_mrr():
    # evidence: segments 1 and 3 of f.
    q = LabeledQuery("q", "x", "semantic", (("f", 1), ("f", 3)))
    results = [
        H(0.0, 10.0),    # rank 1: covers seg 0, not evidence
        H(30.2, 40.0),   # rank 2: covers seg 3  -> first relevant at rank 2
        H(0.0, 10.0, "g"),
        H(20.2, 30.0),
        H(20.2, 30.0),
        H(10.2, 20.0),   # rank 6: covers seg 1 (only within top-10)
    ]
    s = score_query(q, results, REFS)
    assert s.recall == {5: 0.5, 10: 1.0}    # top-5 finds seg 3 only; top-10 finds both
    assert s.hit == {5: 1.0, 10: 1.0}
    assert s.reciprocal_rank == 0.5         # 1 / 2


def test_one_chunk_covering_two_evidence_segments_counts_both():
    q = LabeledQuery("q", "x", "semantic", (("f", 0), ("f", 1)))
    s = score_query(q, [H(0.0, 20.0)], REFS)      # overlaps seg 0 for 10 s and seg 1 for 9.8 s
    assert s.recall == {5: 1.0, 10: 1.0} and s.reciprocal_rank == 1.0


def test_duplicate_results_do_not_inflate_recall():
    q = LabeledQuery("q", "x", "keyword", (("f", 0), ("f", 1)))
    s = score_query(q, [H(0.0, 10.0)] * 10, REFS)
    assert s.recall[10] == 0.5


def test_duplicate_evidence_does_not_inflate_recall():
    q = LabeledQuery("q", "x", "keyword", (("f", 0), ("f", 0), ("f", 1)))
    assert score_query(q, [H(0.0, 10.0)], REFS).recall[10] == 0.5


def test_results_beyond_max_k_are_ignored():
    q = LabeledQuery("q", "x", "keyword", (("f", 1),))
    s = score_query(q, [H(0.0, 10.0)] * 10 + [H(10.2, 20.0)], REFS)  # relevant only at rank 11
    assert s.recall == {5: 0.0, 10: 0.0} and s.reciprocal_rank == 0.0


def test_no_results_and_no_evidence():
    q = LabeledQuery("q", "x", "keyword", (("f", 1),))
    assert score_query(q, [], REFS).recall == {5: 0.0, 10: 0.0}
    with pytest.raises(ValueError):
        score_query(LabeledQuery("q", "x", "keyword", ()), [], REFS)


# ---- speakers ----------------------------------------------------------------------------

def test_speaker_mapping_is_the_best_one_to_one_permutation():
    # diarizer called reference A "S1" and B "S0"
    chunks = {"f": [H(0, 10, speaker="S1"), H(10.2, 20, speaker="S0"), H(20.2, 30, speaker="S1")]}
    assert speaker_mapping(chunks, REFS) == {"f": {"S0": "B", "S1": "A"}}


def test_speaker_mapping_never_maps_two_labels_to_one_reference_speaker():
    chunks = {"f": [H(0, 10, speaker="S0"), H(20.2, 30, speaker="S1")]}  # both actually overlap A
    m = speaker_mapping(chunks, REFS)["f"]
    assert sorted(m.values()) == ["A", "B"]  # one-to-one, even though a greedy map would give A twice


def test_speaker_correct_hand_computed():
    mapping = {"f": {"S0": "B", "S1": "A"}}
    assert speaker_correct(H(0, 10, speaker="S1"), REFS, mapping) is True
    assert speaker_correct(H(0, 10, speaker="S0"), REFS, mapping) is False
    assert speaker_correct(H(8, 19, speaker="S0"), REFS, mapping) is True   # 2 s of A, 8.8 s of B -> B
    assert speaker_correct(H(50, 60, speaker="S0"), REFS, mapping) is None  # no reference speech


# ---- summarize ---------------------------------------------------------------------------

def test_summary_means_and_split_by_kind():
    q1 = score_query(LabeledQuery("a", "x", "keyword", (("f", 0),)), [H(0, 10)], REFS)        # 1.0 / rr 1
    q2 = score_query(LabeledQuery("b", "x", "semantic", (("f", 1),)), [H(0, 10)] * 5 + [H(10.2, 20)], REFS)  # r@5 0, r@10 1, rr 1/6
    s = summarize([q1, q2])
    assert s["overall"] == {"queries": 2, "mrr": round((1 + 1 / 6) / 2, 4), "recall@5": 0.5, "recall@10": 1.0,
                            "hit@5": 0.5, "hit@10": 1.0}
    assert s["keyword"]["recall@5"] == 1.0 and s["semantic"]["recall@5"] == 0.0
    assert summarize([]) == {}
