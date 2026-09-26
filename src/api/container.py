"""Composition root: the only place that imports both infra and application. Models load once, here."""
from __future__ import annotations

import json
import logging
import sys

from api.settings import Settings
from application.chunking import ChunkingConfig
from application.ingest import IngestService
from application.search import SearchService
from infra.audio import TorchcodecDecoder
from infra.diarizer import PyannoteDiarizer
from infra.embedder import SentenceTransformerEmbedder
from infra.postgres import PostgresRepository
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
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    return IngestService(
        decoder=TorchcodecDecoder(),
        transcriber=FasterWhisperTranscriber(settings.whisper_model),
        diarizer=PyannoteDiarizer(settings.diarization_model, settings.hf_token),
        embedder=embedder,
        files=PostgresRepository(settings.database_url),
        chunking=ChunkingConfig(settings.split_soft_min_seconds, settings.split_cap_seconds),
    )


def build_search_service(settings: Settings, embedder: SentenceTransformerEmbedder | None = None) -> SearchService:
    """Search loads the embedder only: no Whisper, no pyannote. Pass a loaded embedder to share it with ingest."""
    return SearchService(
        PostgresRepository(settings.database_url, hnsw_ef_search=settings.hnsw_ef_search),
        embedder or SentenceTransformerEmbedder(settings.embedding_model),
        weights=settings.fusion_weights,
        rrf_k=settings.rrf_k,
        candidate_depth_multiplier=settings.candidate_depth_multiplier,
    )
