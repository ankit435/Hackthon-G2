"""Assign a speaker to every transcript segment (PLAN.md §6.4). High-risk: a bug here corrupts every label."""
from __future__ import annotations

from collections.abc import Sequence

from domain.errors import AlignmentError
from domain.models import AlignedSegment, SpeakerTurn, TranscriptSegment


def _overlap(seg_start: float, seg_end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(seg_end, turn.end) - max(seg_start, turn.start))


def _gap(seg_start: float, seg_end: float, turn: SpeakerTurn) -> float:
    """Distance between two intervals; 0 when they touch or overlap."""
    if turn.end < seg_start:
        return seg_start - turn.end
    if turn.start > seg_end:
        return turn.start - seg_end
    return 0.0


def align(segments: Sequence[TranscriptSegment], turns: Sequence[SpeakerTurn]) -> list[AlignedSegment]:
    """Give each transcript segment the speaker of one diarized turn. Output is sorted by (start, end).

    Contract and edge-case decisions:
    - Primary rule: the turn with the greatest time overlap wins.
    - Overlap tie (exactly equal overlap with two or more turns): the turn that starts
      earliest wins, then the lexicographically smaller speaker label. Arbitrary but
      deterministic, so re-ingesting a file can never change a label.
    - Zero-duration segment (start == end): it has no length to overlap, so it is treated
      as a point. It takes a turn whose closed interval contains the point, with the same
      tie-break (a point on the boundary between two turns goes to the earlier one).
    - No overlap and no containment: the turn nearest by interval gap, with the same
      tie-break. PLAN.md says "nearest by start time". The gap is used because a segment
      that starts 0.1 s after a long turn ends belongs with that turn, not with one that
      starts 2 s later (see PROGRESS.md Decisions Log).
    - Every segment gets a speaker. `None` is impossible: no turns at all raises
      AlignmentError instead of guessing.
    - An empty segment list returns []. A segment with end < start, or a turn with
      end < start, raises AlignmentError (corrupt upstream output, not something to repair).
    """
    if not segments:
        return []
    if not turns:
        raise AlignmentError("diarization produced no speaker turns", stage="align", segments=len(segments))
    for t in turns:
        if t.end < t.start:
            raise AlignmentError("speaker turn ends before it starts", stage="align", start=t.start, end=t.end)
    ordered_turns = sorted(turns, key=lambda t: (t.start, t.speaker))

    aligned = []
    for seg in sorted(segments, key=lambda s: (s.start, s.end)):
        if seg.end < seg.start:
            raise AlignmentError("transcript segment ends before it starts", stage="align", start=seg.start, end=seg.end)

        if seg.end > seg.start:
            best, best_overlap = None, 0.0
            for turn in ordered_turns:
                # strict '>' keeps the earliest turn on an exact tie (ordered_turns is sorted)
                ov = _overlap(seg.start, seg.end, turn)
                if ov > best_overlap:
                    best, best_overlap = turn, ov
        else:
            best = next((t for t in ordered_turns if t.start <= seg.start <= t.end), None)

        if best is None:
            best = min(ordered_turns, key=lambda t: (_gap(seg.start, seg.end, t), t.start, t.speaker))

        aligned.append(AlignedSegment(start=seg.start, end=seg.end, text=seg.text, speaker=best.speaker))
    return aligned
