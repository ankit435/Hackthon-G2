"""Domain models. Stdlib only: no infra type (model object, DB row, numpy array) crosses this line."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4


class Branch(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class DecodedAudio:
    """One file decoded once, then shared by every model that needs the waveform.

    Decoding once matters here: PyAV (faster-whisper) and torchcodec (pyannote) load
    different FFmpeg builds, and a single decode keeps them from both touching a file.
    `samples` is mono float32 in [-1, 1]; adapters may hold an array-like here.
    """
    path: Path
    samples: Sequence[float]
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class AlignedSegment:
    """A transcript segment with its speaker. `speaker` is never empty (PLAN.md §6.4)."""
    start: float
    end: float
    text: str
    speaker: str


@dataclass(frozen=True)
class AudioFile:
    file_name: str
    file_path: str
    checksum: str
    duration_seconds: float
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = None


@dataclass(frozen=True)
class Chunk:
    audio_file_id: UUID
    chunk_index: int
    speaker: str
    text: str
    start_time: float
    end_time: float
    token_count: int
    char_count: int
    id: UUID = field(default_factory=uuid4)
    prev_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class BranchHit:
    """One row of a single branch's ranked list. `rank` is 1-based within that branch."""
    chunk_id: UUID
    rank: int
    score: float


@dataclass(frozen=True)
class FusedHit:
    chunk_id: UUID
    score: float


@dataclass(frozen=True)
class SearchResultItem:
    """A hydrated hit: everything the brief requires (file, timestamp, speaker) plus the text."""
    chunk_id: UUID
    audio_file_id: UUID
    file_name: str
    file_path: str
    speaker: str
    start_time: float
    end_time: float
    text: str
    score: float
