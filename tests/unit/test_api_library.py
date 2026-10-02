"""Library, audio, context, upload and config routes with mocked services (no DB, no models)."""
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from application.ingest import IngestOutcome, IngestStatus
from application.jobs import IngestQueue
from tests.unit.fake_jobs import InMemoryJobRepository
from domain.errors import InvalidInputError, NotFoundError
from domain.models import AudioFile, Chunk, ChunkContext, LibraryFile
from infra.uploads import UploadStore

F = AudioFile(file_name="talk.wav", file_path="/x/talk.wav", checksum="c", duration_seconds=12.5, language="es",
              language_probability=0.97)
CHUNKS = [Chunk(audio_file_id=F.id, chunk_index=i, speaker=f"SPEAKER_0{i}", text=f"hola {i}", start_time=5.0 * i,
                end_time=5.0 * i + 4, token_count=3, char_count=6, language="es") for i in range(2)]


@pytest.fixture
def client(tmp_path):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = MagicMock(embedding_model="BAAI/bge-m3", whisper_model="large-v3-turbo",
                                       diarization_model="pyannote/speaker-diarization-3.1", nvidia_api_key=None)
        app.state.search_service = MagicMock(config={"rrf_k": 60, "reranker": None})
        app.state.library_service = AsyncMock()
        app.state.ingest_service = AsyncMock()
        app.state.upload_store = UploadStore(tmp_path, max_bytes=1000)
        app.state.ingest_queue = IngestQueue(app.state.ingest_service, InMemoryJobRepository())  # not started
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = lifespan
    with TestClient(app) as c:
        yield c
    app.router.lifespan_context = original


def test_list_files(client):
    app.state.library_service.files.return_value = [LibraryFile(F, 2, ("SPEAKER_00", "SPEAKER_01"))]
    [row] = client.get("/files").json()
    assert (row["id"], row["language"], row["chunk_count"], row["speakers"]) == (str(F.id), "es", 2, ["SPEAKER_00", "SPEAKER_01"])


def test_transcript_returns_every_chunk_in_order(client):
    app.state.library_service.transcript.return_value = (F, CHUNKS)
    body = client.get(f"/files/{F.id}").json()
    assert body["file"]["chunk_count"] == 2 and body["file"]["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert [c["chunk_index"] for c in body["chunks"]] == [0, 1] and body["chunks"][1]["start_time"] == 5.0


def test_not_found_maps_to_404(client):
    app.state.library_service.transcript.side_effect = NotFoundError("no such audio file")
    app.state.library_service.context.side_effect = NotFoundError("no such chunk")
    app.state.library_service.audio_path.side_effect = NotFoundError("missing")
    assert client.get(f"/files/{uuid4()}").status_code == 404
    assert client.get(f"/chunks/{uuid4()}/context").status_code == 404
    assert client.get(f"/files/{uuid4()}/audio").status_code == 404


def test_malformed_ids_and_window_are_rejected(client):
    assert client.get("/files/not-a-uuid").status_code == 422
    assert client.get(f"/chunks/{uuid4()}/context?window=9").status_code == 422


def test_chunk_context(client):
    app.state.library_service.context.return_value = ChunkContext(F, (CHUNKS[0],), CHUNKS[1], ())
    body = client.get(f"/chunks/{CHUNKS[1].id}/context?window=1").json()
    assert [c["chunk_index"] for c in body["before"]] == [0] and body["chunk"]["chunk_index"] == 1 and body["after"] == []
    app.state.library_service.context.assert_awaited_with(CHUNKS[1].id, 1)


def test_audio_is_streamed_with_range_support(client, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF" + bytes(96))
    app.state.library_service.audio_path.return_value = wav
    full = client.get(f"/files/{F.id}/audio")
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav" and len(full.content) == 100
    part = client.get(f"/files/{F.id}/audio", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"RIFF"  # seeking in the browser player needs this


def test_upload_returns_queued_jobs_at_once_and_isolates_a_bad_file(client, tmp_path):
    resp = client.post("/ingest/upload", files=[("files", ("a.wav", b"one", "audio/wav")),
                                                ("files", ("notes.txt", b"two", "text/plain")),
                                                ("files", ("b.mp3", b"three", "audio/mpeg"))])
    assert resp.status_code == 202
    jobs = resp.json()["jobs"]
    assert [j["state"] for j in jobs] == ["queued", "failed", "queued"]  # same order as uploaded
    assert [j["position"] for j in jobs] == [1, None, 2]
    assert jobs[1]["outcome"]["stage"] == "upload" and "unsupported" in jobs[1]["outcome"]["error"]
    import asyncio
    queued = [j for j in asyncio.run(app.state.ingest_queue.jobs()) if j.state.value == "queued"]
    assert [Path(j.path).name.split("-", 1)[1] for j in queued] == ["a.wav", "b.mp3"]  # only valid files queued
    assert all(Path(j.path).parent == tmp_path for j in queued)
    app.state.ingest_service.ingest_one.assert_not_awaited()  # nothing ran inside the request


def test_jobs_list_get_and_cancel(client):
    [job] = client.post("/ingest/upload", files=[("files", ("a.wav", b"one", "audio/wav"))]).json()["jobs"]
    assert [j["id"] for j in client.get("/jobs").json()] == [job["id"]]
    assert client.get(f"/jobs/{job['id']}").json()["state"] == "queued"
    assert client.delete(f"/jobs/{job['id']}").json()["state"] == "cancelled"
    missing = uuid4()
    assert client.get(f"/jobs/{missing}").status_code == 404
    assert client.delete(f"/jobs/{missing}").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 422


def test_config_reports_models_and_search_settings(client):
    body = client.get("/config").json()
    assert body["rrf_k"] == 60 and body["reranker"] is None and body["embedding_model"] == "BAAI/bge-m3"
    assert body["answer_enabled"] is False


def test_ui_serves_assets_and_falls_back_to_index_for_deep_links(client, tmp_path, monkeypatch):
    import api.main as main
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)
    assert client.get("/ui/assets/app.js").text == "console.log(1)"
    assert client.get("/ui/files/123").text == "<html>app</html>"  # deep link -> SPA entry
    assert client.get("/ui").text == "<html>app</html>"
    assert client.get("/ui/../secret.txt").text != "nope"  # never escapes dist
    assert client.get("/ui/%2e%2e/secret.txt").text != "nope"


def test_ui_missing_build_is_a_clear_404(client, tmp_path, monkeypatch):
    import api.main as main
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path / "nothing")
    r = client.get("/ui/search")
    assert r.status_code == 404 and "npm run build" in r.json()["detail"]
