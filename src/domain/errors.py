"""Typed domain errors. Adapters wrap library exceptions in these, so nothing infra-specific leaks upward."""
from __future__ import annotations


class DomainError(Exception):
    """Base error carrying structured context (stage, file id, query hash, ...) for logs and HTTP mapping."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.context = context

    def __str__(self) -> str:
        ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
        return f"{super().__str__()} ({ctx})" if ctx else super().__str__()


class ConfigurationError(DomainError):
    """Invalid configuration, e.g. a negative fusion weight or an unknown branch name."""


class InvalidInputError(DomainError):
    """Bad input at a system boundary: missing file, empty query, bad top-k."""


class AudioDecodeError(DomainError):
    pass


class TranscriptionError(DomainError):
    pass


class DiarizationError(DomainError):
    pass


class AlignmentError(DomainError):
    pass


class ChunkingError(DomainError):
    pass


class EmbeddingError(DomainError):
    pass


class RepositoryError(DomainError):
    pass


class AnswerGenerationError(DomainError):
    """NVIDIA answer-generation request failed after deterministic retrieval succeeded."""
