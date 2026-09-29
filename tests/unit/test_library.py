"""LibraryService and UploadStore with fakes / a temp dir: no database, no model."""
import asyncio
import io
import uuid
from pathlib import Path

import pytest

from application.library import LibraryService
from domain.errors import InvalidInputError, NotFoundError
from domain.models import AudioFile, Chunk, LibraryFile
from infra.uploads import UploadStore, safe_name


def make_file(path="/nonexistent.wav"):
    return AudioFile(file_name="a.wav", file_path=path, checksum="c", duration_seconds=60.0, language="en",
                     language_probability=0.99)


def make_chunks(file, n):
    return [Chunk(audio_file_id=file.id, chunk_index=i, speaker=f"SPEAKER_0{i % 2}", text=f"t{i}",
                  start_time=10.0 * i, end_time=10.0 * i + 9, token_count=3, char_count=2, language="en")
            for i in range(n)]


class FakeRepo:
    def __init__(self, files=(), chunks=()):
        self.files = {f.id: f for f in files}
        self.chunks = list(chunks)

    async def list_files(self):
        return [LibraryFile(f, sum(c.audio_file_id == f.id for c in self.chunks), ()) for f in self.files.values()]

    async def get_file(self, fid):
        return self.files.get(fid)

    async def get_chunk(self, cid):
        return next((c for c in self.chunks if c.id == cid), None)

    async def list_by_file(self, fid):
        # scrambled on purpose: the service must not depend on storage order
        return sorted([c for c in self.chunks if c.audio_file_id == fid], key=lambda c: c.chunk_index)


def service(repo):
    return LibraryService(files=repo, chunks=repo)


def test_transcript_returns_file_and_chunks_in_order():
    f = make_file(); cs = make_chunks(f, 4)
    file, chunks = asyncio.run(service(FakeRepo([f], cs)).transcript(f.id))
    assert file == f and [c.chunk_index for c in chunks] == [0, 1, 2, 3]


def test_unknown_file_is_not_found():
    with pytest.raises(NotFoundError):
        asyncio.run(service(FakeRepo()).transcript(uuid.uuid4()))


@pytest.mark.parametrize("target, window, before, after", [
    (0, 2, [], [1, 2]),          # first chunk: nothing before
    (2, 2, [0, 1], [3, 4]),
    (4, 2, [2, 3], []),          # last chunk: nothing after
    (2, 0, [], []),
    (1, 5, [0], [2, 3, 4]),      # window larger than what exists
])
def test_context_windows_clip_at_file_edges(target, window, before, after):
    f = make_file(); cs = make_chunks(f, 5)
    ctx = asyncio.run(service(FakeRepo([f], cs)).context(cs[target].id, window))
    assert ctx.chunk.chunk_index == target and ctx.file == f
    assert [c.chunk_index for c in ctx.before] == before and [c.chunk_index for c in ctx.after] == after


def test_context_never_crosses_into_another_file():
    f, g = make_file(), make_file()
    fc, gc = make_chunks(f, 2), make_chunks(g, 3)
    ctx = asyncio.run(service(FakeRepo([f, g], fc + gc)).context(fc[1].id, 5))
    assert ctx.file == f and [c.id for c in ctx.before] == [fc[0].id] and ctx.after == ()


def test_context_rejects_bad_window_and_unknown_chunk():
    f = make_file(); cs = make_chunks(f, 2)
    with pytest.raises(InvalidInputError):
        asyncio.run(service(FakeRepo([f], cs)).context(cs[0].id, 6))
    with pytest.raises(NotFoundError):
        asyncio.run(service(FakeRepo([f], cs)).context(uuid.uuid4(), 1))


def test_audio_path_serves_only_existing_indexed_files(tmp_path):
    wav = tmp_path / "x.wav"; wav.write_bytes(b"RIFF")
    present, missing = make_file(str(wav)), make_file(str(tmp_path / "gone.wav"))
    svc = service(FakeRepo([present, missing]))
    assert asyncio.run(svc.audio_path(present.id)) == wav
    with pytest.raises(NotFoundError):
        asyncio.run(svc.audio_path(missing.id))
    with pytest.raises(NotFoundError):
        asyncio.run(svc.audio_path(uuid.uuid4()))


# --- UploadStore ---------------------------------------------------------------------------------------

def reader(data: bytes):
    buf = io.BytesIO(data)

    async def read(n):
        return buf.read(n)
    return read


@pytest.mark.parametrize("name, expected", [
    ("../../etc/passwd.wav", "passwd.wav"),
    ("C:\\\\Users\\\\me\\\\talk 1.wav", "talk_1.wav"),
    ("ünïcode name.mp3", "n_code_name.mp3"),
    ("...", "audio"),
])
def test_safe_name_strips_directories_and_odd_characters(name, expected):
    assert safe_name(name) == expected


def test_upload_is_saved_under_a_content_hash_prefix(tmp_path):
    store = UploadStore(tmp_path, max_bytes=1000)
    a = asyncio.run(store.save("talk.wav", reader(b"abc")))
    b = asyncio.run(store.save("talk.wav", reader(b"abc")))
    c = asyncio.run(store.save("talk.wav", reader(b"xyz")))
    assert a == b and a != c and a.read_bytes() == b"abc" and a.parent == tmp_path
    assert a.name.endswith("-talk.wav") and not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("name, data, message", [
    ("notes.txt", b"abc", "unsupported"),
    ("empty.wav", b"", "empty"),
    ("big.wav", b"x" * 1001, "size limit"),
])
def test_bad_uploads_are_rejected_and_leave_nothing_behind(tmp_path, name, data, message):
    with pytest.raises(InvalidInputError, match=message):
        asyncio.run(UploadStore(tmp_path, max_bytes=1000).save(name, reader(data)))
    assert list(tmp_path.iterdir()) == []
