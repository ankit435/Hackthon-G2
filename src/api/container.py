"""Composition root: the only place that imports both infra and application. Models load once, here."""
from __future__ import annotations

import json
import logging
import sys

from api.settings import Settings
from application.answer import AnswerService
from application.chunking import ChunkingConfig
from application.evaluation import EvaluationService
from application.ingest import IngestService
from application.library import LibraryService
from application.search import SearchService
from infra.audio import TorchcodecDecoder
from infra.diarizer import PyannoteDiarizer
from infra.embedder import SentenceTransformerEmbedder
from infra.nvidia import NvidiaAnswerGenerator
from infra.postgres import PostgresJobRepository, PostgresRepository
from infra.reranker import CrossEncoderReranker
from infra.uploads import UploadStore
from infra.whisper import FasterWhisperTranscriber

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra=` fields become top-level keys (PLAN.md §9)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                   "logger": record.name, "msg": record.getMessage()}
        payload.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def build_ingest_service(settings: Settings) -> IngestService:
    embedder = SentenceTransformerEmbedder(settings.embedding_model, device=settings.embedding_device)
    return IngestService(
        decoder=TorchcodecDecoder(),
        transcriber=FasterWhisperTranscriber(settings.whisper_model, language=settings.transcription_language),
        diarizer=PyannoteDiarizer(settings.diarization_model, settings.hf_token),
        embedder=embedder,
        files=PostgresRepository(settings.database_url),
        chunking=ChunkingConfig(settings.split_soft_min_seconds, settings.split_cap_seconds),
        context_embedding=settings.context_embedding,
    )


def build_search_service(settings: Settings, embedder: SentenceTransformerEmbedder | None = None) -> SearchService:
    """Search loads the embedder only: no Whisper, no pyannote. Pass a loaded embedder to share it with ingest."""
    return SearchService(
        PostgresRepository(settings.database_url, hnsw_ef_search=settings.hnsw_ef_search),
        embedder or SentenceTransformerEmbedder(settings.embedding_model, device=settings.embedding_device),
        weights=settings.fusion_weights,
        rrf_k=settings.rrf_k,
        candidate_depth_multiplier=settings.candidate_depth_multiplier,
        reranker=CrossEncoderReranker(settings.reranker_model, device=settings.reranker_device)
        if settings.reranker_model else None,
        rerank_depth=settings.rerank_depth,
    )


def build_evaluation_service(settings: Settings) -> EvaluationService:
    search = build_search_service(settings)
    repo = PostgresRepository(settings.database_url, hnsw_ef_search=settings.hnsw_ef_search)
    return EvaluationService(search, files=repo, chunks=repo)


def build_answer_service(settings: Settings, search: SearchService | None = None) -> AnswerService:
    """Separate stretch endpoint: NVIDIA synthesizes only after standard search completes."""
    return AnswerService(
        search or build_search_service(settings),
        NvidiaAnswerGenerator(settings.nvidia_api_key, base_url=settings.answer_base_url, model=settings.answer_model),
    )


def build_library_service(settings: Settings) -> LibraryService:
    repo = PostgresRepository(settings.database_url)
    return LibraryService(files=repo, chunks=repo)


def build_job_repository(settings: Settings) -> PostgresJobRepository:
    return PostgresJobRepository(settings.database_url)


def build_upload_store(settings: Settings) -> UploadStore:
    return UploadStore(settings.upload_dir, max_bytes=settings.upload_max_mb * 1024 * 1024)
