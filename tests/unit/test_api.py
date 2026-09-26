"""Unit tests for FastAPI routes (PLAN.md §7A)."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from domain.errors import InvalidInputError
from domain.models import SearchResultItem


@pytest.fixture
def client():
    @asynccontextmanager
    async def dummy_lifespan(app):
        app.state.settings = MagicMock()
        app.state.ingest_service = AsyncMock()
        app.state.search_service = AsyncMock()
        app.state.evaluation_service = AsyncMock()
        app.state.search_service.config = {
            "weights": {"keyword": 1.0, "semantic": 1.0},
            "rrf_k": 60,
            "candidate_depth_multiplier": 5,
        }
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = dummy_lifespan

    with TestClient(app) as test_client:
        yield test_client

    app.router.lifespan_context = original_lifespan


def _sample_hit():
    return SearchResultItem(
        chunk_id=uuid4(),
        audio_file_id=uuid4(),
        file_name="audio_01.wav",
        file_path="dataset/audio_01.wav",
        speaker="SPEAKER_00",
        start_time=1.0,
        end_time=5.0,
        text="Rate limiting algorithm test.",
        language="en",
        score=0.015,
    )


def test_search_endpoint_success(client):
    mock_item = _sample_hit()
    app.state.search_service.search.return_value = [mock_item]

    response = client.get("/search?query=rate+limiting&top_k=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["chunk_id"] == str(mock_item.chunk_id)
    assert data[0]["file_name"] == "audio_01.wav"
    assert data[0]["score"] == 0.015
    app.state.search_service.search.assert_called_once_with("rate limiting", 5)


def test_search_endpoint_invalid_input(client):
    app.state.search_service.search.side_effect = InvalidInputError("query must not be empty", stage="search")

    response = client.get("/search?query=")
    assert response.status_code == 400
    assert "query must not be empty" in response.json()["detail"]


def test_keyword_endpoint_success(client):
    mock_item = _sample_hit()
    app.state.search_service.keyword.return_value = [mock_item]

    response = client.get("/search/keyword?query=rate&top_k=5")
    assert response.status_code == 200
    assert response.json()[0]["chunk_id"] == str(mock_item.chunk_id)
    app.state.search_service.keyword.assert_called_once_with("rate", 5)


def test_semantic_endpoint_success(client):
    mock_item = _sample_hit()
    app.state.search_service.semantic.return_value = [mock_item]

    response = client.get("/search/semantic?query=rate&top_k=5")
    assert response.status_code == 200
    assert response.json()[0]["chunk_id"] == str(mock_item.chunk_id)
    app.state.search_service.semantic.assert_called_once_with("rate", 5)


def test_ingest_endpoint_success(client):
    app.state.ingest_service.ingest.return_value = [{"path": "dataset/audio_01.wav", "status": "ingested"}]

    response = client.post("/ingest", json={"paths": ["dataset/audio_01.wav"]})
    assert response.status_code == 200
    assert response.json()["outcomes"][0]["status"] == "ingested"
    app.state.ingest_service.ingest.assert_called_once_with(["dataset/audio_01.wav"])


def test_evaluation_endpoints_success(client):
    app.state.evaluation_service.run.return_value = {"recall_at_5": 0.85}

    response_get = client.get("/evaluation")
    assert response_get.status_code == 200
    assert response_get.json()["summary"]["recall_at_5"] == 0.85

    response_post = client.post("/evaluation")
    assert response_post.status_code == 200
    assert response_post.json()["summary"]["recall_at_5"] == 0.85
