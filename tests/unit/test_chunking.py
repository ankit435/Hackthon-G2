import asyncio

import pytest

from application.chunking import (
    ChunkingConfig,
    ChunkingReport,
    Piece,
    chunk_semantic,
    chunk_sync,
    deterministic_split,
    link,
    merge_turn,
    semantic_split,
    sentences,
)
from domain.models import AlignedSegment as A

CFG = ChunkingConfig(split_soft_min_seconds=20, split_cap_seconds=45)


def P(start, end, text="t", speaker="A"):
    return Piece(speaker, start, end, text)


def spans(pieces):
    return [(round(p.start, 3), round(p.end, 3)) for p in pieces]


class StubEmbedder:
    """Deterministic fake: a sentence's vector is looked up by its first word."""

    def __init__(self, vectors=None, fail=False, wrong_count=False):
        self.vectors, self.fail, self.wrong_count, self.calls = vectors or {}, fail, wrong_count, []

    dimension, max_tokens = 2, 256

    def count_tokens(self, text):
        return len(text.split())

    async def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("model exploded")
        out = [self.vectors.get(t.split()[0], [1.0, 0.0]) for t in texts]
        return out[:-1] if self.wrong_count else out


# ---- merge -------------------------------------------------------------------------------

def test_merge_packs_toward_target_and_stops_once_reached():
    turn = [P(0, 6), P(6.3, 12), P(12.3, 16), P(16.3, 20)]
    # 0-12 (<15) takes the third -> 0-16 (>=15) closes; the rest starts a new chunk
    assert spans(merge_turn(turn)) == [(0, 16), (16.3, 20)]


def test_merge_never_exceeds_cap():
    turn = [P(0, 10), P(10, 29), P(29, 31)]
    # 0-10 + 10-29 = 29 <= 30 ok (still < target? no: 29 >= 15 closes after); 29-31 alone
    assert spans(merge_turn(turn)) == [(0, 29), (29, 31)]
    assert spans(merge_turn([P(0, 10), P(10, 31)])) == [(0, 10), (10, 31)]  # would be 31 > 30


def test_merge_keeps_an_oversized_single_segment_whole():
    assert spans(merge_turn([P(0, 40)])) == [(0, 40)]


def test_alternating_dialogue_is_a_merge_no_op():
    segs = [A(i * 7.0, i * 7.0 + 6.7, f"s{i}.", "S0" if i % 2 == 0 else "S1") for i in range(6)]
    out = chunk_sync(segs, CFG)
    assert [(p.speaker, p.text) for p in out] == [(s.speaker, s.text) for s in segs]


def test_merge_never_crosses_a_speaker_boundary():
    segs = [A(0, 3, "a.", "S0"), A(3, 6, "b.", "S0"), A(6, 9, "c.", "S1"), A(9, 12, "d.", "S0")]
    assert [(p.speaker, p.text) for p in chunk_sync(segs, CFG)] == [("S0", "a. b."), ("S1", "c."), ("S0", "d.")]


def test_whitespace_segments_are_dropped_and_counted():
    report = ChunkingReport()
    out = chunk_sync([A(0, 1, "  ", "S0"), A(1, 2, "hi.", "S0")], CFG, report)
    assert [p.text for p in out] == ["hi."] and report.dropped_empty_segments == 1


# ---- sentences / time apportionment --------------------------------------------------------

def test_time_is_apportioned_by_character_length():
    # "Aaaa." = 5 chars, "Bbbbbbbbbbbbbb." = 15 chars; 20 chars over 10 s -> 2.5 s / 7.5 s
    [s1, s2] = sentences([P(100, 110, "Aaaa. Bbbbbbbbbbbbbb.")])
    assert (s1.start, s1.end, s1.text) == (100, 102.5, "Aaaa.")
    assert (s2.start, s2.end, s2.text) == (102.5, 110, "Bbbbbbbbbbbbbb.")


def test_last_sentence_ends_exactly_at_segment_end():
    parts = sentences([P(0.1, 0.7, "One. Two. Three.")])
    assert parts[-1].end == 0.7 and parts[0].start == 0.1
    assert all(a.end == b.start for a, b in zip(parts, parts[1:]))


@pytest.mark.parametrize("text,expected", [
    ("你好。我们开始吧！", ["你好。", "我们开始吧！"]),                      # CJK: no space after 。
    ("限流器很重要。 我们需要令牌桶？好的", ["限流器很重要。", "我们需要令牌桶？", "好的"]),  # optional space
    ("यह पहला है। यह दूसरा है।", ["यह पहला है।", "यह दूसरा है।"]),          # Devanagari danda
    ("पहला॥ दूसरा", ["पहला॥", "दूसरा"]),                                  # double danda
    ("هل هذا صحيح؟ نعم", ["هل هذا صحيح؟", "نعم"]),                        # Arabic question mark
    ("First one. Second one! Third?", ["First one.", "Second one!", "Third?"]),
    ("version 2.5 is out", ["version 2.5 is out"]),                        # no split without a following space
])
def test_sentence_split_is_script_aware(text, expected):
    assert [p.text for p in sentences([P(0, 10, text)])] == expected


@pytest.mark.parametrize("text", ["你好。我们开始吧！", "यह पहला है। यह दूसरा है।", "Aaaa. Bbbbbbbbbbbbbb."])
def test_apportioned_times_tile_the_segment_exactly(text):
    parts = sentences([P(3.0, 9.0, text)])
    assert parts[0].start == 3.0 and parts[-1].end == 9.0
    assert all(a.end == b.start for a, b in zip(parts, parts[1:]))
    total = sum(len(p.text) for p in parts)
    for p in parts[:-1]:
        assert p.duration == pytest.approx(6.0 * len(p.text) / total)


def test_text_without_terminal_punctuation_is_one_sentence():
    assert [s.text for s in sentences([P(0, 5, "no punctuation here")])] == ["no punctuation here"]


# ---- deterministic split -------------------------------------------------------------------

def ten_second_sentences(n):
    return [P(i * 10.0, i * 10.0 + 10.0, f"s{i}") for i in range(n)]


def test_deterministic_split_respects_cap():
    chunks = deterministic_split(ten_second_sentences(10), cap=45)
    assert all(c.duration <= 45 for c in chunks)
    assert chunks[0].start == 0 and chunks[-1].end == 100


def test_deterministic_split_overlaps_only_short_trailing_sentences():
    sents = [P(0, 20, "a"), P(20, 42, "b"), P(42, 44, "c"), P(44, 60, "d")]
    # chunk 1: a b c (0-44). Overlap: c (2 s) <= 3 s carries; b+c (24 s) does not.
    assert [c.text for c in deterministic_split(sents, cap=45)] == ["a b c", "c d"]


def test_deterministic_split_without_short_trailer_has_no_overlap():
    assert [c.text for c in deterministic_split(ten_second_sentences(6), cap=45)] == ["s0 s1 s2 s3", "s4 s5"]


def test_deterministic_split_keeps_an_oversized_sentence_alone_and_terminates():
    sents = [P(0, 50, "huge"), P(50, 52, "tiny"), P(52, 110, "huge2")]
    assert [c.text for c in deterministic_split(sents, cap=45)] == ["huge", "tiny", "huge2"]


# ---- semantic split ------------------------------------------------------------------------

def test_semantic_split_cuts_at_lowest_similarity_candidate_after_soft_min():
    sents = ten_second_sentences(6)  # boundaries at 10,20,30,40,50 s
    sims = [0.1, 0.9, 0.5, 0.7, 0.9]  # boundary 0 is lowest but before soft min (chunk only 10 s)
    # candidates while < cap: b1 (20 s) 0.9, b2 (30 s) 0.5, b3 (40 s) 0.7 -> overflow at s4 (50 s) -> cut at b2
    assert [c.text for c in semantic_split(sents, sims, CFG)] == ["s0 s1 s2", "s3 s4 s5"]


def test_semantic_split_considers_the_boundary_right_at_the_cap():
    sims = [0.9, 0.9, 0.9, 0.1, 0.9]  # lowest at b3 (40 s), the last legal cut before overflow
    assert [c.text for c in semantic_split(ten_second_sentences(6), sims, CFG)] == ["s0 s1 s2 s3", "s4 s5"]


def test_semantic_split_tie_goes_to_later_boundary():
    sims = [0.5, 0.5, 0.5, 0.5, 0.5]
    assert [c.text for c in semantic_split(ten_second_sentences(6), sims, CFG)] == ["s0 s1 s2 s3", "s4 s5"]


def test_semantic_split_without_candidates_cuts_before_overflow():
    sents = [P(0, 15, "a"), P(15, 60, "b"), P(60, 70, "c")]  # a < soft min; adding b overflows
    # b alone is exactly the 45 s cap; b + c would be 55 s, so b stands alone too
    assert [c.text for c in semantic_split(sents, [0.2, 0.9], CFG)] == ["a", "b", "c"]


def test_semantic_split_chunks_never_exceed_cap_unless_single_sentence():
    sents = ten_second_sentences(20)
    chunks = semantic_split(sents, [0.3 + (i % 3) * 0.2 for i in range(19)], CFG)
    assert all(c.duration <= 45 for c in chunks)
    assert chunks[0].start == 0 and chunks[-1].end == 200
    assert all(a.end <= b.start for a, b in zip(chunks, chunks[1:]))  # no overlap, no gaps lost


def test_semantic_split_rejects_mismatched_similarities():
    with pytest.raises(ValueError):
        semantic_split(ten_second_sentences(3), [0.5], CFG)


# ---- the two chunkers ----------------------------------------------------------------------

def long_turn(topic_change_at=4):
    """One speaker, 6 segments x 10 s, two sentences each; the topic flips after segment `topic_change_at`."""
    words = ["alpha" if i < topic_change_at else "beta" for i in range(6)]
    return [A(i * 10.0, i * 10.0 + 10.0, f"{w} one. {w} two.", "S0") for i, w in enumerate(words)]


def test_chunkers_agree_on_every_transcript_below_the_cap():
    transcripts = [
        [],
        [A(0, 5, "one.", "S0")],
        [A(i * 7.0, i * 7.0 + 6.7, f"s{i}.", f"S{i % 2}") for i in range(20)],
        [A(0, 10, "a.", "S0"), A(10, 20, "b.", "S0"), A(20, 44.9, "c.", "S0"), A(45, 50, "d.", "S1")],
    ]
    for segs in transcripts:
        embedder = StubEmbedder()
        assert asyncio.run(chunk_semantic(segs, CFG, embedder)) == chunk_sync(segs, CFG)
        assert embedder.calls == []  # below the cap the embedder is never consulted


def test_semantic_chunker_splits_long_turn_at_topic_change_with_one_batched_call():
    embedder = StubEmbedder({"alpha": [1.0, 0.0], "beta": [0.0, 1.0]})
    report = ChunkingReport()
    out = asyncio.run(chunk_semantic(long_turn(topic_change_at=3), CFG, embedder, report))
    assert len(embedder.calls) == 1 and len(embedder.calls[0]) == 12
    assert [p.text.split()[0] for p in out] == ["alpha", "beta"]
    assert (out[0].end, out[1].start) == (30.0, 30.0)
    assert (report.long_turns, report.semantic_splits, report.fallback_splits) == (1, 1, 0)


@pytest.mark.parametrize("embedder", [StubEmbedder(fail=True), StubEmbedder(wrong_count=True)])
def test_embedder_failure_falls_back_to_deterministic_and_is_counted(embedder, caplog):
    report = ChunkingReport()
    out = asyncio.run(chunk_semantic(long_turn(), CFG, embedder, report))
    expected = chunk_sync(long_turn(), CFG)
    assert out == expected
    assert (report.long_turns, report.semantic_splits, report.fallback_splits) == (1, 0, 1)
    assert any("deterministic fallback" in r.message for r in caplog.records)


def test_chunks_are_single_speaker_and_time_ordered():
    later = [A(s.start + 70, s.end + 70, s.text, s.speaker) for s in long_turn()[:2]]
    segs = long_turn() + [A(60.3, 65, "reply.", "S1")] + later
    for chunks in (chunk_sync(segs, CFG), asyncio.run(chunk_semantic(segs, CFG, StubEmbedder()))):
        assert all(c.start < c.end for c in chunks)
        assert [c.start for c in chunks] == sorted(c.start for c in chunks)


# ---- link ----------------------------------------------------------------------------------

def test_link_chains_ids():
    rows = link(3)
    (a, pa, na), (b, pb, nb), (c, pc, nc) = rows
    assert (pa, na, pb, nb, pc, nc) == (None, b, a, c, b, None)
    assert len({a, b, c}) == 3


def test_link_edge_counts():
    assert link(0) == []
    [(only, prev, nxt)] = link(1)
    assert prev is None and nxt is None
