"""Saves uploaded audio to disk so the ingest pipeline can read it by path (POST /ingest/upload)."""
from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from domain.errors import InvalidInputError

# Anything ffmpeg/torchcodec decodes; the whitelist only stops obviously wrong files early.
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".webm", ".aac", ".mp4"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_BLOCK = 1 << 20


def safe_name(name: str) -> str:
    """Basename only (no directories, so no path traversal), with unusual characters replaced."""
    base = _UNSAFE.sub("_", Path(name.replace("\\", "/")).name).strip("._") or "audio"
    return base[-120:]


class UploadStore:
    """Writes each upload to `<root>/<sha256 prefix>-<safe name>`.

    The content hash prefix makes identical uploads land on the same path (ingest then reports them as
    skipped via its own checksum check), and different files with the same name never overwrite each other.
    """

    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root, self._max = Path(root), max_bytes

    async def save(self, name: str, read: Callable[[int], Awaitable[bytes]]) -> Path:
        clean = safe_name(name)
        if Path(clean).suffix.lower() not in AUDIO_EXTENSIONS:
            raise InvalidInputError("unsupported audio file type", stage="upload", file=name,
                                    allowed=",".join(sorted(AUDIO_EXTENSIONS)))
        self._root.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=self._root, delete=False, suffix=".part") as tmp:
            try:
                while block := await read(_BLOCK):
                    size += len(block)
                    if size > self._max:
                        raise InvalidInputError("file exceeds the upload size limit", stage="upload", file=name,
                                                max_bytes=self._max)
                    digest.update(block)
                    tmp.write(block)
            except BaseException:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise
        if size == 0:
            Path(tmp.name).unlink(missing_ok=True)
            raise InvalidInputError("empty file", stage="upload", file=name)
        target = self._root / f"{digest.hexdigest()[:12]}-{clean}"
        Path(tmp.name).replace(target)
        return target
