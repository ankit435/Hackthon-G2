"""Ingestion pipeline (PLAN.md §6): checksum -> decode -> transcribe -> diarize -> align -> chunk -> embed -> persist."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from application.alignment import align_words
from application.chunking import ChunkingConfig, ChunkingReport, chunk_semantic, link
from domain.errors import DomainError, InvalidInputError
from domain.models import AudioFile, Chunk
from domain.ports import AudioDecoder, AudioFileRepository, Diarizer, Embedder, Transcriber

log = logging.getLogger(__name__)

NUM_SPEAKERS = 2  # every file is a known two-speaker conversation (Q3); removes a whole error class
# Below this detection confidence the language (and so stemming config and search slice) may be wrong:
# ingest proceeds, but it is logged and recorded on the outcome rather than trusted silently.
LANGUAGE_CONFIDENCE_WARN = 0.5


class IngestStatus(str, Enum):
    INGESTED = "ingested"
    SKIPPED_EXISTING = "skipped_existing"
    FAILED = "failed"


@dataclass
class IngestOutcome:
    path: str
    status: IngestStatus
    audio_file_id: str | None = None
    chunk_count: int = 0
    duration_seconds: float | None = None
    language: str | None = None
    language_probability: float | None = None
    stage: str | None = None
    error_type: str | None = None
    error: str | None = None
    stage_seconds: dict[str, float] = field(default_factory=dict)
    chunking: dict[str, int] = field(default_factory=dict)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _Stage:
    """Times a stage, logs start/end, and records which stage was running if it raises."""

    def __init__(self, outcome: IngestOutcome, name: str) -> None:
        self.outcome, self.name = outcome, name

    def __enter__(self):
        self.outcome.stage, self.t0 = self.name, time.perf_counter()
        log.info("ingest.stage.start", extra={"event": f"ingest.{self.name}.start", "file": self.outcome.path})
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.perf_counter() - self.t0
        self.outcome.stage_seconds[self.name] = round(elapsed, 3)
        if exc_type is None:
            log.info("ingest.stage.end", extra={"event": f"ingest.{self.name}.end", "file": self.outcome.path,
                                                "duration_s": round(elapsed, 3)})
        return False


class IngestService:
    def __init__(self, decoder: AudioDecoder, transcriber: Transcriber, diarizer: Diarizer, embedder: Embedder,
                 files: AudioFileRepository, chunking: ChunkingConfig) -> None:
        self._decoder, self._transcriber, self._diarizer = decoder, transcriber, diarizer
        self._embedder, self._files, self._chunking = embedder, files, chunking

    async def ingest(self, paths: Sequence[str | Path]) -> list[IngestOutcome]:
        """Each file independently: one failure never aborts the batch (PLAN.md §7A)."""
        outcomes = []
        for p in paths:
            outcomes.append(await self.ingest_one(Path(p)))
        summary = {s.value: sum(o.status is s for o in outcomes) for s in IngestStatus}
        log.info("ingest.batch.end", extra={"event": "ingest.batch.end", "files": len(outcomes), **summary})
        return outcomes

    async def ingest_one(self, path: Path) -> IngestOutcome:
        outcome = IngestOutcome(path=str(path), status=IngestStatus.FAILED)
        try:
            await self._run(path, outcome)
        except DomainError as e:
            outcome.error_type, outcome.error = type(e).__name__, str(e)
            log.error("ingest.file.failed", extra={"event": "ingest.failed", "file": str(path), "stage": outcome.stage,
                                                   "error_type": outcome.error_type, "error": outcome.error})
        except Exception as e:  # noqa: BLE001 — per-file isolation: recorded in the outcome and logged with traceback
            outcome.error_type, outcome.error = type(e).__name__, str(e)
            log.exception("ingest.file.failed", extra={"event": "ingest.failed", "file": str(path),
                                                       "stage": outcome.stage, "error_type": outcome.error_type})
        return outcome

    async def _run(self, path: Path, outcome: IngestOutcome) -> None:
        with _Stage(outcome, "validate"):
            if not path.is_file():
                raise InvalidInputError("not a readable file", stage="validate", file=str(path))
            checksum = await asyncio.to_thread(sha256_file, path)
            existing = await self._files.find_by_checksum(checksum)
        if existing:
            outcome.status, outcome.stage = IngestStatus.SKIPPED_EXISTING, None
            outcome.audio_file_id, outcome.duration_seconds = str(existing.id), existing.duration_seconds
            log.info("ingest.skipped", extra={"event": "ingest.skipped", "file": str(path), "checksum": checksum})
            return

        with _Stage(outcome, "decode"):
            audio = await asyncio.to_thread(self._decoder.decode, path)
            outcome.duration_seconds = round(audio.duration_seconds, 3)
        with _Stage(outcome, "transcribe"):
            transcript = await asyncio.to_thread(self._transcriber.transcribe, audio)
            segments = transcript.segments
            outcome.language = transcript.language
            outcome.language_probability = round(transcript.language_probability, 4)
            log.info("ingest.language", extra={"event": "ingest.language", "file": str(path),
                                               "language": transcript.language,
                                               "language_probability": outcome.language_probability})
            if transcript.language_probability < LANGUAGE_CONFIDENCE_WARN:
                log.warning("language detection has low confidence",
                            extra={"event": "ingest.language.low_confidence", "file": str(path),
                                   "language": transcript.language,
                                   "language_probability": outcome.language_probability,
                                   "threshold": LANGUAGE_CONFIDENCE_WARN})
        with _Stage(outcome, "diarize"):
            turns = await asyncio.to_thread(self._diarizer.diarize, audio, NUM_SPEAKERS)
        with _Stage(outcome, "align"):
            aligned = align_words(segments, turns)
        with _Stage(outcome, "chunk"):
            report = ChunkingReport()
            pieces = await chunk_semantic(aligned, self._chunking, self._embedder, report)
            outcome.chunking = vars(report).copy()
            log.info("ingest.chunk.report", extra={"event": "ingest.chunk.report", "file": str(path),
                                                   "segments": len(segments), "turns": len(turns),
                                                   "chunks": len(pieces), **outcome.chunking})
        with _Stage(outcome, "embed"):
            vectors = await self._embedder.embed([p.text for p in pieces])

        audio_file = AudioFile(file_name=path.name, file_path=str(path.resolve()), checksum=checksum,
                               duration_seconds=audio.duration_seconds, language=transcript.language,
                               language_probability=transcript.language_probability)
        chunks = []
        for i, (piece, vector, (cid, prev_id, next_id)) in enumerate(zip(pieces, vectors, link(len(pieces)))):
            tokens = self._embedder.count_tokens(piece.text)
            if tokens > self._embedder.max_tokens:
                log.warning("chunk exceeds embedder window; tail is truncated in its embedding",
                            extra={"event": "ingest.chunk.truncated", "file": str(path), "chunk_index": i,
                                   "tokens": tokens, "max_tokens": self._embedder.max_tokens})
            chunks.append(Chunk(id=cid, audio_file_id=audio_file.id, chunk_index=i, speaker=piece.speaker,
                                text=piece.text, start_time=piece.start, end_time=piece.end, token_count=tokens,
                                char_count=len(piece.text), language=transcript.language,
                                prev_chunk_id=prev_id, next_chunk_id=next_id,
                                embedding=tuple(vector)))
        with _Stage(outcome, "persist"):
            await self._files.add_with_chunks(audio_file, chunks)

        outcome.status, outcome.stage = IngestStatus.INGESTED, None
        outcome.audio_file_id, outcome.chunk_count = str(audio_file.id), len(chunks)
