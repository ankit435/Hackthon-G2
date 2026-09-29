"""FastAPI entry point implementing the five required endpoints (PLAN.md §7A)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, List
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.container import (build_answer_service, build_evaluation_service, build_ingest_service,
                           build_library_service, build_search_service, build_upload_store, configure_logging)
from api.settings import load_settings
from application.ingest import IngestOutcome, IngestStatus
from domain.errors import ConfigurationError, InvalidInputError, NotFoundError
from domain.models import AudioFile, Chunk

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
AUDIO_MEDIA_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
                     ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".webm": "audio/webm",
                     ".aac": "audio/aac"}


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


class FileSummaryResponse(BaseModel):
    id: str
    file_name: str
    language: str
    language_probability: float
    duration_seconds: float
    created_at: datetime | None
    chunk_count: int | None = None
    speakers: list[str] | None = None


class ChunkResponse(BaseModel):
    id: str
    chunk_index: int
    speaker: str
    text: str
    start_time: float
    end_time: float
    language: str
    prev_chunk_id: str | None
    next_chunk_id: str | None


class TranscriptResponse(BaseModel):
    file: FileSummaryResponse
    chunks: list[ChunkResponse]


class ChunkContextResponse(BaseModel):
    file: FileSummaryResponse
    before: list[ChunkResponse]
    chunk: ChunkResponse
    after: list[ChunkResponse]


def _file_out(f: AudioFile, chunk_count: int | None = None, speakers: tuple[str, ...] | None = None) -> FileSummaryResponse:
    return FileSummaryResponse(id=str(f.id), file_name=f.file_name, language=f.language,
                               language_probability=f.language_probability, duration_seconds=f.duration_seconds,
                               created_at=f.created_at, chunk_count=chunk_count,
                               speakers=list(speakers) if speakers is not None else None)


def _chunk_out(c: Chunk) -> ChunkResponse:
    return ChunkResponse(id=str(c.id), chunk_index=c.chunk_index, speaker=c.speaker, text=c.text,
                         start_time=c.start_time, end_time=c.end_time, language=c.language,
                         prev_chunk_id=str(c.prev_chunk_id) if c.prev_chunk_id else None,
                         next_chunk_id=str(c.next_chunk_id) if c.next_chunk_id else None)


class EvaluationResponse(BaseModel):
    config: dict[str, Any]
    summary: dict[str, Any]


class AnswerRequest(BaseModel):
    query: str = Field(..., description="Question to answer from retrieved audio evidence")
    top_k: int = Field(default=5, ge=1, le=10, description="Retrieved evidence segments to consider")


class AnswerCitation(BaseModel):
    number: int
    chunk_id: str
    audio_file_id: str
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
    app.state.library_service = build_library_service(settings)
    app.state.upload_store = build_upload_store(settings)
    yield


app = FastAPI(
    title="Audio Hybrid Search API",
    description="Hybrid keyword + semantic search over multi-speaker audio conversations.",
    version="1.0.0",
    lifespan=lifespan,
)




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
        from infra.dataset import corrected_references, golden_files, query_set
        queries, meta = query_set("en")
        files = golden_files()
        checksums = {f["audio_id"]: f["sha256"] for f in files}
        file_names = {f["audio"]: f["audio_id"] for f in files}
        eval_result = await app.state.evaluation_service.run(queries, corrected_references(), checksums, file_names)
        config = {**app.state.search_service.config, "embedding_model": app.state.settings.embedding_model}
        return EvaluationResponse(config=config, summary=eval_result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@app.post("/evaluation", response_model=EvaluationResponse, tags=["evaluation"], summary="Run evaluation suite (POST)")
async def run_evaluation_post():
    """Runs retrieval evaluation on the query set and returns quality metrics."""
    try:
        from infra.dataset import corrected_references, golden_files, query_set
        queries, meta = query_set("en")
        files = golden_files()
        checksums = {f["audio_id"]: f["sha256"] for f in files}
        file_names = {f["audio"]: f["audio_id"] for f in files}
        eval_result = await app.state.evaluation_service.run(queries, corrected_references(), checksums, file_names)
        config = {**app.state.search_service.config, "embedding_model": app.state.settings.embedding_model}
        return EvaluationResponse(config=config, summary=eval_result)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e



@app.post("/answer", response_model=AnswerResponse, tags=["answer"],
          summary="Optional NVIDIA LLM answer grounded in hybrid-search results. ")
async def answer_from_audio(payload: AnswerRequest):
    """Separate from /search: deterministic retrieval first, NVIDIA synthesis second."""
    try:
        result = await app.state.answer_service.answer(payload.query, payload.top_k)
        return AnswerResponse(
            answer=result.answer,
            citations=[AnswerCitation(number=index, chunk_id=str(item.chunk_id), audio_file_id=str(item.audio_file_id),
                                       file_name=item.file_name, speaker=item.speaker,
                                       start_time=item.start_time, end_time=item.end_time,
                                       language=item.language, text=item.text)
                       for index, item in enumerate(result.sources, start=1)],
        )
    except InvalidInputError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


# --- Library: browse what is indexed (read-only views for the UI) -------------------------------------

@app.get("/files", response_model=List[FileSummaryResponse], tags=["library"], summary="List indexed audio files")
async def list_files():
    """Every indexed file with its detected language, duration, chunk count and speakers."""
    return [_file_out(f.file, f.chunk_count, f.speakers) for f in await app.state.library_service.files()]


@app.get("/files/{audio_file_id}", response_model=TranscriptResponse, tags=["library"],
         summary="Full transcript of one file (all chunks, in order)")
async def get_transcript(audio_file_id: UUID):
    try:
        file, chunks = await app.state.library_service.transcript(audio_file_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    speakers = tuple(sorted({c.speaker for c in chunks}))
    return TranscriptResponse(file=_file_out(file, len(chunks), speakers), chunks=[_chunk_out(c) for c in chunks])


@app.get("/files/{audio_file_id}/audio", tags=["library"], summary="Stream the audio of an indexed file",
         response_class=FileResponse)
async def get_audio(audio_file_id: UUID):
    """Serves only files the index knows (never an arbitrary path). Supports HTTP range requests for seeking."""
    try:
        path = await app.state.library_service.audio_path(audio_file_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return FileResponse(path, media_type=AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@app.get("/chunks/{chunk_id}/context", response_model=ChunkContextResponse, tags=["library"],
         summary="A chunk with its neighbouring chunks")
async def get_chunk_context(chunk_id: UUID, window: int = Query(2, ge=0, le=5, description="Chunks on each side")):
    try:
        ctx = await app.state.library_service.context(chunk_id, window)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return ChunkContextResponse(file=_file_out(ctx.file), before=[_chunk_out(c) for c in ctx.before],
                                chunk=_chunk_out(ctx.chunk), after=[_chunk_out(c) for c in ctx.after])


@app.post("/ingest/upload", tags=["ingest"], summary="Upload audio files and ingest them")
async def upload_and_ingest(files: List[UploadFile] = File(..., description="One or more audio files")):
    """Saves each upload, then ingests the saved files as one batch (same pipeline and outcomes as /ingest).

    A rejected upload (wrong type, empty, too large) becomes a `failed` outcome for that file only; the rest
    of the batch still runs. Synchronous: large files take minutes (transcription + diarization).
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no files uploaded")
    outcomes: list[IngestOutcome | None] = []
    saved: list[tuple[int, Path]] = []
    for i, upload in enumerate(files):
        try:
            saved.append((i, await app.state.upload_store.save(upload.filename or "audio", upload.read)))
            outcomes.append(None)
        except InvalidInputError as e:
            outcomes.append(IngestOutcome(path=upload.filename or "", status=IngestStatus.FAILED, stage="upload",
                                          error_type=type(e).__name__, error=str(e)))
        finally:
            await upload.close()
    if saved:
        for (i, _), outcome in zip(saved, await app.state.ingest_service.ingest([p for _, p in saved])):
            outcomes[i] = outcome
    return {"outcomes": outcomes}


@app.get("/config", tags=["system"], summary="Active search configuration and models")
async def get_config():
    s = app.state.settings
    return {**app.state.search_service.config, "embedding_model": s.embedding_model,
            "whisper_model": s.whisper_model, "diarization_model": s.diarization_model,
            "answer_enabled": bool(s.nvidia_api_key)}


# The built React UI (frontend/dist), when present, is served at /ui by the same process.
# Real files (assets) are served as-is; any other /ui path gets index.html so the browser router can
# handle deep links such as /ui/files/<id> on reload. Paths are confined to frontend/dist.
@app.get("/ui", include_in_schema=False)
@app.get("/ui/{path:path}", include_in_schema=False)
async def serve_ui(path: str = ""):
    dist = FRONTEND_DIST.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="UI not built: run `npm install && npm run build` in frontend/")
    candidate = (dist / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(dist):
        return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
