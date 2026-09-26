"""FastAPI entry point implementing the five required endpoints (PLAN.md §7A)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, List

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.container import (build_answer_service, build_evaluation_service, build_ingest_service,
                           build_search_service, configure_logging)
from api.settings import load_settings
from domain.errors import ConfigurationError, InvalidInputError


class IngestRequest(BaseModel):
    paths: List[str] = Field(..., description="List of file paths to ingest", json_schema_extra={"example": ["dataset/audio_01_rate_limiter.wav"]})


class SearchResultResponse(BaseModel):
    chunk_id: str
    audio_file_id: str
    file_name: str
    file_path: str
    speaker: str
    text: str
    start_time: float
    end_time: float
    language: str
    score: float


class EvaluationResponse(BaseModel):
    config: dict[str, Any]
    summary: dict[str, Any]


class AnswerRequest(BaseModel):
    query: str = Field(..., description="Question to answer from retrieved audio evidence")
    top_k: int = Field(default=5, ge=1, le=10, description="Retrieved evidence segments to consider")


class AnswerCitation(BaseModel):
    number: int
    file_name: str
    speaker: str
    start_time: float
    end_time: float
    language: str
    text: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[AnswerCitation]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.ingest_service = build_ingest_service(settings)
    app.state.search_service = build_search_service(settings)
    app.state.answer_service = build_answer_service(settings, app.state.search_service)
    app.state.evaluation_service = build_evaluation_service(settings)
    yield


app = FastAPI(
    title="Audio Hybrid Search API",
    description="Hybrid keyword + semantic search over multi-speaker audio conversations.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/answer", response_model=AnswerResponse, tags=["answer"],
          summary="Optional NVIDIA LLM answer grounded in hybrid-search results")
async def answer_from_audio(payload: AnswerRequest):
    """Separate from /search: deterministic retrieval first, NVIDIA synthesis second."""
    try:
        result = await app.state.answer_service.answer(payload.query, payload.top_k)
        return AnswerResponse(
            answer=result.answer,
            citations=[AnswerCitation(number=index, file_name=item.file_name, speaker=item.speaker,
                                       start_time=item.start_time, end_time=item.end_time,
                                       language=item.language, text=item.text)
                       for index, item in enumerate(result.sources, start=1)],
        )
    except InvalidInputError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/ingest", tags=["ingest"], summary="Ingest audio files into the search index")
async def ingest_audio_files(payload: IngestRequest):
    """Ingests a list of audio files. One failure will not abort the batch."""
    if not payload.paths:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="paths list must not be empty")
    try:
        outcomes = await app.state.ingest_service.ingest(payload.paths)
        return {"outcomes": outcomes}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@app.get("/search", response_model=List[SearchResultResponse], tags=["search"], summary="The graded hybrid search path")
async def search(query: str = Query(..., description="Search query string"), top_k: int = Query(10, ge=1, le=50)):
    """Runs hybrid search (keyword + semantic branches fused with weighted RRF)."""
    try:
        results = await app.state.search_service.search(query, top_k)
        return [
            SearchResultResponse(
                chunk_id=str(r.chunk_id),
                audio_file_id=str(r.audio_file_id),
                file_name=r.file_name,
                file_path=r.file_path,
                speaker=r.speaker,
                text=r.text,
                start_time=r.start_time,
                end_time=r.end_time,
                language=r.language,
                score=r.score,
            )
            for r in results
        ]
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@app.get("/search/keyword", response_model=List[SearchResultResponse], tags=["search"], summary="Diagnostic: keyword search branch alone")
async def search_keyword(query: str = Query(..., description="Search query string"), top_k: int = Query(10, ge=1, le=50)):
    """Diagnostic endpoint for keyword search branch alone."""
    try:
        results = await app.state.search_service.keyword(query, top_k)
        return [
            SearchResultResponse(
                chunk_id=str(r.chunk_id),
                audio_file_id=str(r.audio_file_id),
                file_name=r.file_name,
                file_path=r.file_path,
                speaker=r.speaker,
                text=r.text,
                start_time=r.start_time,
                end_time=r.end_time,
                language=r.language,
                score=r.score,
            )
            for r in results
        ]
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@app.get("/search/semantic", response_model=List[SearchResultResponse], tags=["search"], summary="Diagnostic: semantic search branch alone")
async def search_semantic(query: str = Query(..., description="Search query string"), top_k: int = Query(10, ge=1, le=50)):
    """Diagnostic endpoint for semantic search branch alone."""
    try:
        results = await app.state.search_service.semantic(query, top_k)
        return [
            SearchResultResponse(
                chunk_id=str(r.chunk_id),
                audio_file_id=str(r.audio_file_id),
                file_name=r.file_name,
                file_path=r.file_path,
                speaker=r.speaker,
                text=r.text,
                start_time=r.start_time,
                end_time=r.end_time,
                language=r.language,
                score=r.score,
            )
            for r in results
        ]
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@app.get("/evaluation", response_model=EvaluationResponse, tags=["evaluation"], summary="Run evaluation suite (GET)")
async def run_evaluation_get():
    """Runs retrieval evaluation on the query set and returns quality metrics."""
    try:
        eval_result = await app.state.evaluation_service.run()
        config = {**app.state.search_service.config, "embedding_model": app.state.settings.embedding_model}
        return EvaluationResponse(config=config, summary=eval_result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@app.post("/evaluation", response_model=EvaluationResponse, tags=["evaluation"], summary="Run evaluation suite (POST)")
async def run_evaluation_post():
    """Runs retrieval evaluation on the query set and returns quality metrics."""
    try:
        eval_result = await app.state.evaluation_service.run()
        config = {**app.state.search_service.config, "embedding_model": app.state.settings.embedding_model}
        return EvaluationResponse(config=config, summary=eval_result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
