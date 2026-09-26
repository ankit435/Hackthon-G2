"""Merge -> split -> link (PLAN.md §6). High-risk: boundary and time-apportionment bugs misplace timestamps.

Interpretation of §6 (recorded in PROGRESS.md Decisions Log): a *turn* is a maximal run of
consecutive segments from one speaker.
  - A turn no longer than the split cap is merge-packed at segment boundaries (target ~15 s,
    hard cap ~30 s). Both chunkers share this path, which is what makes them agree below the cap.
  - A turn longer than the split cap is cut into sentences and split: at meaning boundaries
    (semantic chunker) or greedily at the cap with a small overlap (deterministic chunker).

Times inside a segment: the transcriber gives segment-level timestamps only, so a segment's
duration is apportioned across its sentences in proportion to character length. This is a
known approximation (SOLUTION.md).
"""
from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from domain.models import AlignedSegment
from domain.ports import Embedder

log = logging.getLogger(__name__)

MERGE_TARGET_SECONDS = 15.0
MERGE_CAP_SECONDS = 30.0
OVERLAP_MAX_SECONDS = 3.0  # deterministic split only
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Piece:
    """A timed span of one speaker's text: a segment, a sentence, or a finished chunk."""
    speaker: str
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class ChunkingConfig:
    split_soft_min_seconds: float
    split_cap_seconds: float

    def __post_init__(self) -> None:
        if not 0 < self.split_soft_min_seconds < self.split_cap_seconds:
            raise ValueError("need 0 < split_soft_min_seconds < split_cap_seconds")


@dataclass
class ChunkingReport:
    long_turns: int = 0
    semantic_splits: int = 0
    fallback_splits: int = 0
    dropped_empty_segments: int = 0


def _join(pieces: Sequence[Piece]) -> Piece:
    return Piece(pieces[0].speaker, pieces[0].start, max(p.end for p in pieces), " ".join(p.text for p in pieces))


def speaker_turns(segments: Sequence[AlignedSegment], report: ChunkingReport) -> list[list[Piece]]:
    """Group consecutive same-speaker segments into turns. Whitespace-only segments are dropped and counted."""
    turns: list[list[Piece]] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            report.dropped_empty_segments += 1
            continue
        piece = Piece(seg.speaker, seg.start, seg.end, text)
        if turns and turns[-1][-1].speaker == seg.speaker:
            turns[-1].append(piece)
        else:
            turns.append([piece])
    return turns


def merge_turn(turn: Sequence[Piece]) -> list[Piece]:
    """Pack one speaker's consecutive segments into chunks near MERGE_TARGET, never over MERGE_CAP.

    - Segments are appended while the chunk is still shorter than the target and the result
      would not exceed the cap (duration = first start to last end, gaps included).
    - A single segment longer than the cap stays whole; merge never cuts inside a segment.
    - Never crosses a speaker boundary: the input is one speaker's turn.
    - Rapid alternating dialogue gives one-segment turns, so this is a no-op there.
    """
    chunks: list[Piece] = []
    current: list[Piece] = []
    for piece in turn:
        if current:
            span_if_added = max(piece.end, current[-1].end) - current[0].start
            if current[-1].end - current[0].start >= MERGE_TARGET_SECONDS or span_if_added > MERGE_CAP_SECONDS:
                chunks.append(_join(current))
                current = []
        current.append(piece)
    if current:
        chunks.append(_join(current))
    return chunks


def sentences(turn: Sequence[Piece]) -> list[Piece]:
    """Split each segment into sentences and apportion its duration by character length.

    Sentence k of a segment [s, e] with character lengths L_1..L_n gets
    [s + (e-s)*sum(L_<k)/sum(L), s + (e-s)*sum(L_<=k)/sum(L)]. The last sentence's end is set
    to exactly e, so floating-point error never shifts a segment boundary.
    """
    out: list[Piece] = []
    for seg in turn:
        parts = [p for p in (s.strip() for s in _SENTENCE_END.split(seg.text)) if p]
        total = sum(len(p) for p in parts)
        cursor, consumed = seg.start, 0
        for i, part in enumerate(parts):
            consumed += len(part)
            end = seg.end if i == len(parts) - 1 else seg.start + seg.duration * consumed / total
            out.append(Piece(seg.speaker, cursor, end, part))
            cursor = end
    return out


def deterministic_split(sents: Sequence[Piece], cap: float) -> list[Piece]:
    """Greedy sentence packing up to `cap` seconds, with <= OVERLAP_MAX_SECONDS of trailing overlap.

    - A chunk takes sentences until the next one would push it past the cap.
    - The next chunk starts with the previous chunk's trailing sentences whose total duration
      is <= OVERLAP_MAX_SECONDS (possibly none), so a fact on the boundary appears in both chunks.
    - A single sentence longer than the cap becomes its own chunk (it cannot be cut further).
    - Termination: the overlap never includes a whole chunk, so each chunk advances by at least
      one new sentence.
    """
    chunks: list[Piece] = []
    i = 0
    while i < len(sents):
        j = i + 1
        while j < len(sents) and sents[j].end - sents[i].start <= cap:
            j += 1
        chunks.append(_join(sents[i:j]))
        if j >= len(sents):
            break
        k = j
        while k - 1 > i and sents[j - 1].end - sents[k - 1].start <= OVERLAP_MAX_SECONDS:
            k -= 1
        i = k
    return chunks


def semantic_split(sents: Sequence[Piece], similarity: Sequence[float], cfg: ChunkingConfig) -> list[Piece]:
    """Split at the biggest topic change inside the [soft_min, cap] window. No overlap.

    `similarity[b]` is the cosine similarity between sentence b and sentence b+1, i.e. of
    boundary b (after sentence b). While accumulating a chunk from sentence `start`:
    - Once the chunk has lasted >= soft_min, every later boundary is a split candidate.
    - When adding the next sentence would exceed the cap, cut at the lowest-similarity
      candidate seen so far. On an exact tie the LATER boundary wins (longer, fewer chunks).
      With no candidate yet (sentences too long to reach soft_min under the cap), cut right
      before the sentence that would overflow.
    - A single sentence longer than the cap becomes its own chunk.
    - The remainder after the last cut is the final chunk, however short.
    """
    if len(similarity) != len(sents) - 1:
        raise ValueError(f"need {len(sents) - 1} similarities, got {len(similarity)}")
    chunks: list[Piece] = []
    start = 0
    while start < len(sents):
        best_boundary, best_sim = None, math.inf
        cut = None
        for j in range(start, len(sents)):
            if j + 1 == len(sents):
                break  # last sentence: no boundary after it; the remainder is the final chunk
            # Register boundary j BEFORE the overflow check: cutting right at the cap is itself a
            # legal candidate and may be the lowest-similarity point in the window.
            if sents[j].end - sents[start].start >= cfg.split_soft_min_seconds and similarity[j] <= best_sim:
                best_boundary, best_sim = j, similarity[j]  # '<=' makes the later boundary win ties
            if sents[j + 1].end - sents[start].start > cfg.split_cap_seconds:
                cut = best_boundary if best_boundary is not None else j  # no candidate: cut before the overflow
                break
        end = len(sents) - 1 if cut is None else cut
        chunks.append(_join(sents[start:end + 1]))
        start = end + 1
    return chunks


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def chunk_sync(segments: Sequence[AlignedSegment], cfg: ChunkingConfig,
               report: ChunkingReport | None = None) -> list[Piece]:
    """Embedder-free chunker: merge short turns, split long ones deterministically. The baseline and the fallback."""
    report = report if report is not None else ChunkingReport()
    out: list[Piece] = []
    for turn in speaker_turns(segments, report):
        if turn[-1].end - turn[0].start <= cfg.split_cap_seconds:
            out.extend(merge_turn(turn))
        else:
            report.long_turns += 1
            out.extend(deterministic_split(sentences(turn), cfg.split_cap_seconds))
    return out


async def chunk_semantic(segments: Sequence[AlignedSegment], cfg: ChunkingConfig, embedder: Embedder,
                         report: ChunkingReport | None = None) -> list[Piece]:
    """Same as chunk_sync for turns under the cap. Long turns are split at meaning boundaries.

    One batched embed call per long turn. Any embedder failure falls back to the
    deterministic split for that turn (WARNING, counted): a smarter split must never fail an ingest.
    """
    report = report if report is not None else ChunkingReport()
    out: list[Piece] = []
    for turn in speaker_turns(segments, report):
        if turn[-1].end - turn[0].start <= cfg.split_cap_seconds:
            out.extend(merge_turn(turn))
            continue
        report.long_turns += 1
        sents = sentences(turn)
        try:
            vectors = await embedder.embed([s.text for s in sents])
            if len(vectors) != len(sents):
                raise ValueError(f"embedder returned {len(vectors)} vectors for {len(sents)} sentences")
            sims = [_cosine(vectors[i], vectors[i + 1]) for i in range(len(sents) - 1)]
            out.extend(semantic_split(sents, sims, cfg))
            report.semantic_splits += 1
        except Exception as e:  # noqa: BLE001 — isolation is the contract; failure is logged and counted
            log.warning("semantic split failed; using deterministic fallback",
                        extra={"stage": "chunk", "error_type": type(e).__name__, "error": str(e),
                               "turn_start": turn[0].start, "sentences": len(sents)})
            out.extend(deterministic_split(sents, cfg.split_cap_seconds))
            report.fallback_splits += 1
    return out


def link(count: int) -> list[tuple[UUID, UUID | None, UUID | None]]:
    """(id, prev_id, next_id) for `count` chunks in order; the ends have None neighbours."""
    ids = [uuid4() for _ in range(count)]
    return [(ids[i], ids[i - 1] if i else None, ids[i + 1] if i + 1 < count else None) for i in range(count)]
