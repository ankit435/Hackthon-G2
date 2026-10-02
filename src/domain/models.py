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
class Word:
    start: float
    end: float
    text: str  # as emitted by the transcriber, including its leading space


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()  # empty when the transcriber gave no word timings


@dataclass(frozen=True)
class Transcript:
    """One file's transcript. Whisper detects ONE language per file from its first 30 s."""
    segments: list[TranscriptSegment]
    language: str  # ISO 639-1 code as reported by the transcriber, e.g. "en", "es", "zh"
    language_probability: float  # detection confidence in [0, 1]; 1.0 when the language was forced


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
    language: str
    language_probability: float
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
    language: str
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
    language: str
    score: float


@dataclass(frozen=True)
class AnswerResult:
    """LLM answer plus the retrieval results that are its authoritative citations."""
    answer: str
    sources: tuple[SearchResultItem, ...]


# --- evaluation (PLAN.md §10): shared by the application metric core and the infra dataset loader ---

@dataclass(frozen=True)
class RefSegment:
    index: int
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class Hit:
    """The parts of a search result evaluation needs. `file` is the reference file key (audio_id)."""
    file: str
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class LabeledQuery:
    id: str
    text: str
    kind: str  # "keyword" | "semantic"
    evidence: tuple[tuple[str, int], ...]  # (audio_id, reference segment index)


@dataclass(frozen=True)
class LibraryFile:
    """An indexed file as the library lists it: the file record plus its index statistics."""
    file: AudioFile
    chunk_count: int
    speakers: tuple[str, ...]


@dataclass(frozen=True)
class ChunkContext:
    """One chunk with up to `window` neighbours on each side, in transcript order."""
    file: AudioFile
    before: tuple[Chunk, ...]
    chunk: Chunk
    after: tuple[Chunk, ...]


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    INGESTED = "ingested"
    SKIPPED_EXISTING = "skipped_existing"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED_JOB_STATES = frozenset({JobState.INGESTED, JobState.SKIPPED_EXISTING, JobState.FAILED, JobState.CANCELLED})


@dataclass
class IngestJob:
    """One uploaded file in the persistent ingest queue."""

    file_name: str
    path: str
    id: UUID = field(default_factory=uuid4)
    state: JobState = JobState.QUEUED
    stage: str | None = None  # live pipeline stage while running
    attempts: int = 0
    outcome: dict | None = None  # the ingest outcome, JSON-ready
    position: int | None = None  # 1-based place in line while queued; filled in on read
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
