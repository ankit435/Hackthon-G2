"""Domain ports. Application services depend on these; infra implements them (PLAN.md §5).

Adapters must raise the matching domain error from `domain.errors`, never a library exception.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from domain.models import (
    AudioFile,
    BranchHit,
    Chunk,
    DecodedAudio,
    IngestJob,
    JobState,
    LibraryFile,
    SearchResultItem,
    SpeakerTurn,
    Transcript,
)


class AudioDecoder(Protocol):
    def decode(self, path: Path) -> DecodedAudio:
        """Decode to mono float32 once per file. Raises AudioDecodeError."""
        ...


class Transcriber(Protocol):
    def transcribe(self, audio: DecodedAudio) -> Transcript:
        """Timestamped segments (no speakers) plus the detected language. Raises TranscriptionError."""
        ...


class Diarizer(Protocol):
    def diarize(self, audio: DecodedAudio, num_speakers: int) -> list[SpeakerTurn]:
        """Speaker turns, no text. Speaker labels are arbitrary per file. Raises DiarizationError."""
        ...


class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def max_tokens(self) -> int:
        """Input beyond this many tokens is silently truncated by the model."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens as the model sees them, special tokens included."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One batched call; output order matches input order. Raises EmbeddingError."""
        ...


class Reranker(Protocol):
    """Cross-encoder: reads the query and each passage TOGETHER, so it scores relevance directly
    rather than comparing two independently computed vectors (PLAN.md §11 item 5)."""

    @property
    def model_name(self) -> str: ...

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """One batched call; one score per passage, input order, higher = more relevant. Raises RerankError."""
        ...


class AudioFileRepository(Protocol):
    async def find_by_checksum(self, checksum: str) -> AudioFile | None: ...

    async def add_with_chunks(self, audio_file: AudioFile, chunks: Sequence[Chunk]) -> None:
        """Persist the file record and all its chunks in ONE transaction; no partial writes."""
        ...

    async def list_files(self) -> list[LibraryFile]:
        """Every indexed file with its chunk count and speakers, ordered by file name."""
        ...

    async def get_file(self, audio_file_id: UUID) -> AudioFile | None: ...


class ChunkRepository(Protocol):
    async def keyword_search(self, query: str, limit: int) -> list[BranchHit]:
        """Full-text branch, best first, 1-based ranks. Uses the same text search config as the index."""
        ...

    async def semantic_search(self, query_embedding: Sequence[float], limit: int) -> list[BranchHit]:
        """Vector branch, best first, 1-based ranks, similarity (higher is better) as score."""
        ...

    async def hydrate(self, chunk_ids: Sequence[UUID]) -> list[SearchResultItem]:
        """Chunk + containing file for exactly these ids (score left at 0.0 for the caller to set)."""
        ...

    async def list_by_file(self, audio_file_id: UUID) -> list[Chunk]: ...

    async def get_chunk(self, chunk_id: UUID) -> Chunk | None: ...


class AnswerGenerator(Protocol):
    async def answer(self, query: str, context: str) -> str:
        """Generate an answer solely from numbered retrieved context."""
        ...


class JobRepository(Protocol):
    """Durable FIFO queue of ingest jobs, safe to share between processes."""

    async def add(self, job: IngestJob) -> IngestJob: ...

    async def claim_next(self) -> IngestJob | None:
        """Atomically marks the oldest queued job running (attempts + 1) and returns it; None if none."""
        ...

    async def heartbeat(self, job_id: UUID, stage: str | None) -> None: ...

    async def finish(self, job_id: UUID, state: JobState, outcome: dict | None) -> None: ...

    async def cancel(self, job_id: UUID) -> IngestJob | None:
        """Cancels the job if still queued; returns it in its current state, None if unknown."""
        ...

    async def get(self, job_id: UUID) -> IngestJob | None: ...

    async def list_jobs(self, finished_limit: int) -> list[IngestJob]:
        """Every queued/running job plus the newest `finished_limit` finished ones, oldest first."""
        ...

    async def recover_stale(self, stale_seconds: float, max_attempts: int) -> int:
        """Re-queues running jobs whose heartbeat is older than `stale_seconds` (their process died);
        ones that already used `max_attempts` are failed instead. Returns how many rows changed."""
        ...
