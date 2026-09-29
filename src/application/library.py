"""Browsing the index: the file library, full transcripts, a chunk with its context, and the audio path.

Read-only views over the repositories for the UI. No retrieval or ranking logic lives here.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from domain.errors import InvalidInputError, NotFoundError
from domain.models import AudioFile, Chunk, ChunkContext, LibraryFile
from domain.ports import AudioFileRepository, ChunkRepository

MAX_CONTEXT_WINDOW = 5


class LibraryService:
    def __init__(self, files: AudioFileRepository, chunks: ChunkRepository) -> None:
        self._files, self._chunks = files, chunks

    async def files(self) -> list[LibraryFile]:
        return await self._files.list_files()

    async def _file(self, audio_file_id: UUID) -> AudioFile:
        found = await self._files.get_file(audio_file_id)
        if found is None:
            raise NotFoundError("no such audio file", stage="library", audio_file_id=str(audio_file_id))
        return found

    async def transcript(self, audio_file_id: UUID) -> tuple[AudioFile, list[Chunk]]:
        """The file and every chunk in transcript order (chunk_index)."""
        file = await self._file(audio_file_id)
        return file, await self._chunks.list_by_file(audio_file_id)

    async def context(self, chunk_id: UUID, window: int = 2) -> ChunkContext:
        """The chunk plus up to `window` chunks before and after it in the same file.

        Neighbours come from the file's chunk_index order rather than by following prev/next links,
        so one broken link can never hide the rest of the context.
        """
        if isinstance(window, bool) or not isinstance(window, int) or not 0 <= window <= MAX_CONTEXT_WINDOW:
            raise InvalidInputError(f"window must be an integer in 0..{MAX_CONTEXT_WINDOW}", stage="library", window=window)
        chunk = await self._chunks.get_chunk(chunk_id)
        if chunk is None:
            raise NotFoundError("no such chunk", stage="library", chunk_id=str(chunk_id))
        file = await self._file(chunk.audio_file_id)
        ordered = await self._chunks.list_by_file(chunk.audio_file_id)
        i = next(n for n, c in enumerate(ordered) if c.id == chunk.id)
        return ChunkContext(file=file, before=tuple(ordered[max(0, i - window):i]), chunk=ordered[i],
                            after=tuple(ordered[i + 1:i + 1 + window]))

    async def audio_path(self, audio_file_id: UUID) -> Path:
        """Path of the stored audio for a file the index knows. Only indexed files are ever served."""
        path = Path((await self._file(audio_file_id)).file_path)
        if not path.is_file():
            raise NotFoundError("audio file is indexed but missing on disk", stage="library",
                                audio_file_id=str(audio_file_id), path=str(path))
        return path
