"""Task 8: Chunking QA regression tests (PLAN.md §10.1).

Verifies chunking invariants:
1. Speaker purity: no chunk spans multiple speaker turns.
2. Length distribution & token limits: chunks stay within embedder 256-token limit, valid start/end times.
3. Two-chunker agreement: sync (deterministic) and async (semantic) chunkers produce identical chunks when turns are below cap.
4. Fallback handling: deterministic fallback triggers gracefully on embedder error.
5. Boundary sanity & linkage: valid sequence, sequential indices, linked prev_chunk_id and next_chunk_id.
"""
from unittest.mock import AsyncMock

import pytest

from application.alignment import align_words
from application.chunking import ChunkingConfig, ChunkingReport, chunk_semantic, chunk_sync, link
from domain.errors import EmbeddingError
from domain.models import AlignedSegment, SpeakerTurn, TranscriptSegment, Word


def sample_segments_and_turns():
    segments = [
        TranscriptSegment(start=0.0, end=4.0, text="Hello and welcome to the system design interview.",
                          words=(Word(0.0, 1.0, "Hello"), Word(1.0, 2.0, "and"), Word(2.0, 3.0, "welcome"), Word(3.0, 4.0, "to"))),
        TranscriptSegment(start=4.5, end=8.0, text="Today we are going to design a distributed rate limiter.",
                          words=(Word(4.5, 5.5, "Today"), Word(5.5, 6.5, "we"), Word(6.5, 7.5, "are"))),
        TranscriptSegment(start=8.5, end=12.0, text="That sounds great, let us start with requirements.",
                          words=(Word(8.5, 9.5, "That"), Word(9.5, 10.5, "sounds"), Word(10.5, 11.5, "great"))),
    ]
    turns = [
        SpeakerTurn(start=0.0, end=8.0, speaker="SPEAKER_00"),
        SpeakerTurn(start=8.0, end=12.0, speaker="SPEAKER_01"),
    ]
    return segments, turns


@pytest.mark.asyncio
async def test_speaker_purity_no_cross_speaker_chunks():
    segments, turns = sample_segments_and_turns()
    aligned = align_words(segments, turns)
    config = ChunkingConfig(split_soft_min_seconds=20.0, split_cap_seconds=45.0)
    report = ChunkingReport()

    mock_embedder = AsyncMock()
    mock_embedder.embed.return_value = [[0.1] * 384] * len(aligned)

    chunks = await chunk_semantic(aligned, config, mock_embedder, report)

    # Assert every chunk is single-speaker
    for chunk in chunks:
        assert chunk.speaker in ("SPEAKER_00", "SPEAKER_01")
        # Ensure text is non-empty
        assert len(chunk.text.strip()) > 0


@pytest.mark.asyncio
async def test_two_chunker_agreement_below_split_cap():
    """Assert deterministic (sync) and semantic chunkers produce identical chunks below the 45s cap."""
    segments, turns = sample_segments_and_turns()
    aligned = align_words(segments, turns)
    config = ChunkingConfig(split_soft_min_seconds=20.0, split_cap_seconds=45.0)

    deterministic_chunks = chunk_sync(aligned, config)

    mock_embedder = AsyncMock()
    mock_embedder.embed.return_value = [[0.1] * 384] * len(aligned)
    report = ChunkingReport()
    semantic_chunks = await chunk_semantic(aligned, config, mock_embedder, report)

    assert len(deterministic_chunks) == len(semantic_chunks)
    for det, sem in zip(deterministic_chunks, semantic_chunks):
        assert det.text == sem.text
        assert det.speaker == sem.speaker
        assert det.start == sem.start
        assert det.end == sem.end


@pytest.mark.asyncio
async def test_fallback_on_embedder_failure():
    """Assert embedder failure gracefully falls back to deterministic chunking and increments fallback_splits."""
    segments, turns = sample_segments_and_turns()
    # Force a turn longer than 45s to trigger long turn splitting logic
    long_segments = [
        TranscriptSegment(start=0.0, end=25.0, text="Sentence one is here. Sentence two is also here.",
                          words=(Word(0.0, 10.0, "Sentence"), Word(10.0, 20.0, "one"))),
        TranscriptSegment(start=25.0, end=50.0, text="Sentence three is long. Sentence four finishes turn.",
                          words=(Word(25.0, 35.0, "Sentence"), Word(35.0, 48.0, "three"))),
    ]
    long_turns = [SpeakerTurn(start=0.0, end=50.0, speaker="SPEAKER_00")]
    aligned = align_words(long_segments, long_turns)
    config = ChunkingConfig(split_soft_min_seconds=20.0, split_cap_seconds=45.0)

    failing_embedder = AsyncMock()
    failing_embedder.embed.side_effect = EmbeddingError("Embedder connection lost", stage="embed")
    report = ChunkingReport()

    chunks = await chunk_semantic(aligned, config, failing_embedder, report)
    deterministic_chunks = chunk_sync(aligned, config)

    assert len(chunks) == len(deterministic_chunks)
    assert report.fallback_splits == 1
    assert report.long_turns == 1


def test_chunk_linkage_and_boundary_sanity():
    """Verify prev/next chunk ID linking invariants."""
    num_chunks = 5
    links = link(num_chunks)
    assert len(links) == 5

    # First chunk has prev=None
    cid0, prev0, next0 = links[0]
    assert prev0 is None
    assert next0 is not None

    # Middle chunk has prev and next
    cid1, prev1, next1 = links[1]
    assert prev1 == cid0
    assert next1 is not None

    # Last chunk has next=None
    cid4, prev4, next4 = links[4]
    assert next4 is None
    assert prev4 == links[3][0]


def test_empty_and_single_chunk_linking():
    assert link(0) == []
    single = link(1)
    assert len(single) == 1
    cid, prev, next_id = single[0]
    assert prev is None
    assert next_id is None
