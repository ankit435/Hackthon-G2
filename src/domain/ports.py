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
    SearchResultItem,
    SpeakerTurn,
    TranscriptSegment,
)


class AudioDecoder(Protocol):
    def decode(self, path: Path) -> DecodedAudio:
        """Decode to mono float32 once per file. Raises AudioDecodeError."""
        ...


class Transcriber(Protocol):
    def transcribe(self, audio: DecodedAudio) -> list[TranscriptSegment]:
        """Timestamped text segments, no speakers. Raises TranscriptionError."""
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


class AudioFileRepository(Protocol):
    async def find_by_checksum(self, checksum: str) -> AudioFile | None: ...

    async def add_with_chunks(self, audio_file: AudioFile, chunks: Sequence[Chunk]) -> None:
        """Persist the file record and all its chunks in ONE transaction; no partial writes."""
        ...


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
