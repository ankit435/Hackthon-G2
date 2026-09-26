"""Assign speakers to transcript text (PLAN.md §6.4). High-risk: a bug here corrupts every label.

Word-level by default (PROGRESS.md Decisions Log, 2026-09-26). Whisper segments can run across a
speaker change, and segment-level assignment then gives the other speaker's words the wrong
label. Measured: 104/313 chunks were < 90% speaker-pure. So every word is assigned individually
and segments are cut wherever the speaker changes.
"""
from __future__ import annotations

from collections.abc import Sequence

from domain.errors import AlignmentError
from domain.models import AlignedSegment, SpeakerTurn, TranscriptSegment


def _overlap(start: float, end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(end, turn.end) - max(start, turn.start))


def _gap(start: float, end: float, turn: SpeakerTurn) -> float:
    """Distance between two intervals; 0 when they touch or overlap."""
    if turn.end < start:
        return start - turn.end
    if turn.start > end:
        return turn.start - end
    return 0.0


def _prepare_turns(turns: Sequence[SpeakerTurn]) -> list[SpeakerTurn]:
    for t in turns:
        if t.end < t.start:
            raise AlignmentError("speaker turn ends before it starts", stage="align", start=t.start, end=t.end)
    return sorted(turns, key=lambda t: (t.start, t.speaker))


def speaker_for(start: float, end: float, ordered_turns: Sequence[SpeakerTurn]) -> str:
    """The one speaker-assignment rule, shared by segment- and word-level alignment.

    `ordered_turns` must be non-empty and sorted by (start, speaker).
    - Greatest time overlap wins.
    - Overlap tie → the earliest-starting turn, then the smaller speaker label. Arbitrary but
      deterministic, so a re-ingest never changes a label.
    - Zero-duration span (start == end) is a point: it takes a turn whose closed interval
      contains it (on a shared boundary, the earlier turn).
    - No overlap and no containment → the nearest turn by interval gap, with the same tie-break.
      (PLAN.md says "nearest by start time"; the gap is used because a span starting 0.1 s after
      a long turn ends belongs to that turn, not to one starting 2 s later.)
    - end < start raises AlignmentError: corrupt upstream output is not repaired here.
    """
    if end < start:
        raise AlignmentError("span ends before it starts", stage="align", start=start, end=end)
    best = None
    if end > start:
        best_overlap = 0.0
        for turn in ordered_turns:
            ov = _overlap(start, end, turn)
            if ov > best_overlap:  # strict '>' keeps the earliest turn on an exact tie
                best, best_overlap = turn, ov
    else:
        best = next((t for t in ordered_turns if t.start <= start <= t.end), None)
    if best is None:
        best = min(ordered_turns, key=lambda t: (_gap(start, end, t), t.start, t.speaker))
    return best.speaker


def align(segments: Sequence[TranscriptSegment], turns: Sequence[SpeakerTurn]) -> list[AlignedSegment]:
    """Speaker per segment, ignoring word timings. The fallback, and the pre-2026-09-26 behaviour."""
    if not segments:
        return []
    if not turns:
        raise AlignmentError("diarization produced no speaker turns", stage="align", segments=len(segments))
    ordered = _prepare_turns(turns)
    return [AlignedSegment(start=s.start, end=s.end, text=s.text, speaker=speaker_for(s.start, s.end, ordered))
            for s in sorted(segments, key=lambda s: (s.start, s.end))]


def align_words(segments: Sequence[TranscriptSegment], turns: Sequence[SpeakerTurn]) -> list[AlignedSegment]:
    """Speaker per word, then cut each segment wherever consecutive words change speaker.

    - Each word is assigned with `speaker_for` (same rule as segments).
    - Consecutive same-speaker words inside ONE transcript segment form one aligned segment:
      start = first word's start, end = last word's end, text = the words joined as emitted.
      Runs never cross transcript segments. Downstream chunking already merges same-speaker
      neighbours, so there is nothing to gain by merging here.
    - A segment with no word timings falls back to segment-level assignment, whole.
    - Whitespace-only runs are passed through, not dropped: the chunker is the single place
      that drops empty text, and it counts what it drops (ChunkingReport.dropped_empty_segments).
    - No smoothing: a single word assigned to the other speaker becomes its own tiny segment.
      That is deliberate. It is either correct or a diarizer boundary error, and either way it
      must be measurable rather than hidden (PROGRESS.md).
    Output is sorted by (start, end).
    """
    if not segments:
        return []
    if not turns:
        raise AlignmentError("diarization produced no speaker turns", stage="align", segments=len(segments))
    ordered = _prepare_turns(turns)

    aligned: list[AlignedSegment] = []
    for seg in sorted(segments, key=lambda s: (s.start, s.end)):
        if not seg.words:
            aligned.append(AlignedSegment(seg.start, seg.end, seg.text, speaker_for(seg.start, seg.end, ordered)))
            continue
        run_speaker, run = None, []
        for word in seg.words:
            speaker = speaker_for(word.start, word.end, ordered)
            if run and speaker != run_speaker:
                aligned.append(_from_words(run, run_speaker))
                run = []
            run_speaker = speaker
            run.append(word)
        aligned.append(_from_words(run, run_speaker))
    return aligned


def _from_words(words, speaker: str) -> AlignedSegment:
    return AlignedSegment(start=words[0].start, end=words[-1].end, text="".join(w.text for w in words), speaker=speaker)
