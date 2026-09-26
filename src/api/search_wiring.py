"""Composition for the search path. Kept apart from api/container.py (ingest wiring) only to avoid a
merge conflict while Task 4 was in flight; fold `build_search_service` into container.py when merging.

Search loads the embedder only: no Whisper, no pyannote.
"""
from __future__ import annotations

from api.settings import Settings
from application.search import SearchService
from infra.embedder import SentenceTransformerEmbedder
from infra.postgres import PostgresRepository


def build_search_service(settings: Settings, embedder: SentenceTransformerEmbedder | None = None) -> SearchService:
    """Pass an already-loaded embedder to share one model instance with ingestion."""
    return SearchService(
        PostgresRepository(settings.database_url, hnsw_ef_search=settings.hnsw_ef_search),
        embedder or SentenceTransformerEmbedder(settings.embedding_model),
        weights=settings.fusion_weights,
        rrf_k=settings.rrf_k,
        candidate_depth_multiplier=settings.candidate_depth_multiplier,
    )
