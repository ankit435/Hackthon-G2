import pytest

from application.alignment import align, align_words
from domain.errors import AlignmentError
from domain.models import SpeakerTurn as T
from domain.models import TranscriptSegment as S
from domain.models import Word as W

TURNS = [T(0.0, 5.0, "A"), T(5.0, 12.0, "B"), T(15.0, 20.0, "A")]


def speakers(segments, turns=TURNS):
    return [a.speaker for a in align(segments, turns)]


def test_hand_computed_example():
    # seg 1: 3-7 overlaps A by 2.0, B by 2.0 -> tie -> earlier turn A
    # seg 2: 4-9 overlaps A by 1.0, B by 4.0 -> B
    # seg 3: 12.5-14 overlaps nothing; gap to B = 0.5, to A(15) = 1.0 -> B
    # seg 4: 14.8-14.9 overlaps nothing; gap to A(15) = 0.1, to B = 2.8 -> A
    segs = [S(3, 7, "x"), S(4, 9, "y"), S(12.5, 14, "z"), S(14.8, 14.9, "w")]
    assert speakers(segs) == ["A", "B", "B", "A"]


def test_greatest_overlap_wins():
    assert speakers([S(4.0, 11.0, "x")]) == ["B"]


def test_exact_tie_goes_to_earlier_turn_regardless_of_input_order():
    assert speakers([S(3, 7, "x")], list(reversed(TURNS))) == ["A"]


def test_tie_between_simultaneous_turns_uses_speaker_label():
    turns = [T(0, 10, "SPEAKER_01"), T(0, 10, "SPEAKER_00")]
    assert speakers([S(1, 2, "x")], turns) == ["SPEAKER_00"]


def test_zero_duration_segment_inside_a_turn():
    assert speakers([S(8.0, 8.0, "x")]) == ["B"]


def test_zero_duration_segment_on_a_shared_boundary_goes_to_earlier_turn():
    assert speakers([S(5.0, 5.0, "x")]) == ["A"]


def test_zero_duration_segment_in_a_gap_uses_nearest():
    assert speakers([S(14.0, 14.0, "x")]) == ["A"]  # gap 1.0 to A(15) vs 2.0 to B


def test_equidistant_gap_tie_goes_to_earlier_turn():
    assert speakers([S(13.5, 13.5, "x")]) == ["B"]  # 1.5 from B's end, 1.5 from A's start


def test_segment_touching_a_turn_only_at_an_endpoint_uses_the_gap_rule():
    assert speakers([S(12.0, 13.0, "x")]) == ["B"]  # zero overlap, gap 0 to B


def test_every_segment_gets_a_speaker_and_order_is_by_time():
    out = align([S(16, 18, "c"), S(0, 1, "a"), S(6, 7, "b")], TURNS)
    assert [a.text for a in out] == ["a", "b", "c"] and all(a.speaker for a in out)


def test_text_and_times_pass_through_unchanged():
    [a] = align([S(1.25, 2.5, " hello there ")], TURNS)
    assert (a.start, a.end, a.text) == (1.25, 2.5, " hello there ")


def test_empty_segments_return_empty():
    assert align([], TURNS) == []


def test_no_turns_is_an_error_not_a_none_speaker():
    with pytest.raises(AlignmentError, match="no speaker turns"):
        align([S(0, 1, "x")], [])


def test_inverted_segment_is_an_error():
    with pytest.raises(AlignmentError, match="span ends before"):
        align([S(2, 1, "x")], TURNS)


def test_inverted_turn_is_an_error():
    with pytest.raises(AlignmentError, match="turn ends before"):
        align([S(0, 1, "x")], [T(3, 2, "A")])


def test_overlapping_diarizer_turns_pick_larger_overlap():
    turns = [T(0, 10, "A"), T(8, 12, "B")]  # pyannote may emit overlapping speech
    assert speakers([S(7, 11, "x")], turns) == ["A"]  # A: 3.0, B: 3.0 -> tie -> A
    assert speakers([S(8.5, 11, "x")], turns) == ["B"]  # A: 1.5, B: 2.5


# ---- word-level alignment ---------------------------------------------------------------

def words_seg(*words):
    return S(words[0][0], words[-1][1], "".join(w[2] for w in words), tuple(W(*w) for w in words))


def test_segment_crossing_a_turn_change_is_cut_at_the_word_boundary():
    # the observed failure: one Whisper segment holds the end of A's turn and the start of B's
    seg = words_seg((3.0, 3.8, " cache"), (3.9, 4.8, " and"), (4.85, 4.95, " abuse."), (5.2, 5.9, " Exactly,"),
                    (6.0, 6.5, " naive"))
    out = align_words([seg], TURNS)
    assert [(a.speaker, a.text, a.start, a.end) for a in out] == [
        ("A", " cache and abuse.", 3.0, 4.95), ("B", " Exactly, naive", 5.2, 6.5)]


def test_segment_without_words_falls_back_to_segment_level():
    assert [a.speaker for a in align_words([S(4.0, 11.0, "x")], TURNS)] == ["B"]


def test_word_rule_is_the_segment_rule():
    # each word, aligned alone, must get the same speaker as align() gives the equivalent segment
    words = [(3, 7, " tie"), (4, 9, " b"), (12.5, 14, " gapB"), (14.8, 14.9, " gapA"), (5.0, 5.0, " point")]
    for w in words:
        assert [a.speaker for a in align_words([words_seg(w)], TURNS)] == [a.speaker for a in align([S(*w)], TURNS)]


def test_single_flipped_word_is_kept_not_smoothed():
    seg = words_seg((1.0, 2.0, " one"), (4.9, 5.4, " two"), (2.0, 3.0, " three"))  # middle word overlaps B more
    assert [a.speaker for a in align_words([seg], TURNS)] == ["A", "B", "A"]


def test_runs_never_cross_transcript_segments_and_output_is_time_ordered():
    s1 = words_seg((0.0, 1.0, " a"), (1.0, 2.0, " b"))
    s2 = words_seg((2.5, 3.0, " c"))
    out = align_words([s2, s1], TURNS)
    assert [a.text for a in out] == [" a b", " c"]


def test_whitespace_only_word_runs_pass_through_for_the_chunker_to_count():
    seg = words_seg((1.0, 2.0, " "), (6.0, 7.0, " real"))
    assert [(a.speaker, a.text) for a in align_words([seg], TURNS)] == [("A", " "), ("B", " real")]


def test_word_level_errors_match_segment_level():
    assert align_words([], TURNS) == []
    with pytest.raises(AlignmentError, match="no speaker turns"):
        align_words([words_seg((0, 1, " x"))], [])
    with pytest.raises(AlignmentError, match="span ends before"):
        align_words([words_seg((2, 1, " x"))], TURNS)
