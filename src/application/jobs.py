"""Background ingest queue: uploads return at once and a single worker ingests the files one by one.

One worker on purpose: transcription, diarization and embedding each saturate the CPU/GPU, so running
files in parallel only makes every file slower. Jobs live in memory; a restart forgets them (the files
already indexed stay indexed, and a re-upload of one is skipped by checksum).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from application.ingest import IngestOutcome, IngestService, IngestStatus

log = logging.getLogger(__name__)


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    INGESTED = "ingested"
    SKIPPED_EXISTING = "skipped_existing"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = {JobState.INGESTED, JobState.SKIPPED_EXISTING, JobState.FAILED, JobState.CANCELLED}


@dataclass
class IngestJob:
    file_name: str
    path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # Shared with the running ingest, so `outcome.stage` is the live stage while the job runs.
    outcome: IngestOutcome | None = None


class IngestQueue:
    def __init__(self, ingest: IngestService, keep_finished: int = 200) -> None:
        self._ingest, self._keep = ingest, keep_finished
        self._jobs: dict[str, IngestJob] = {}
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="ingest-queue")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def submit(self, path: Path, file_name: str | None = None) -> IngestJob:
        job = IngestJob(file_name=file_name or path.name, path=str(path))
        self._jobs[job.id] = job
        self._pending.put_nowait(job.id)
        log.info("ingest.job.queued", extra={"event": "ingest.job.queued", "job_id": job.id, "file": job.path})
        return job

    def record_failure(self, file_name: str, outcome: IngestOutcome) -> IngestJob:
        """A file rejected before it could be queued (e.g. bad upload) still shows up in the job list."""
        now = time.time()
        job = IngestJob(file_name=file_name, path=outcome.path, state=JobState.FAILED, started_at=now,
                        finished_at=now, outcome=outcome)
        self._jobs[job.id] = job
        self._trim()
        return job

    def cancel(self, job_id: str) -> IngestJob | None:
        """Cancels a queued job; a running or finished one is left as is. None when the id is unknown."""
        job = self._jobs.get(job_id)
        if job and job.state is JobState.QUEUED:
            job.state, job.finished_at = JobState.CANCELLED, time.time()
        return job

    def get(self, job_id: str) -> IngestJob | None:
        return self._jobs.get(job_id)

    def jobs(self) -> list[IngestJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at)

    def position(self, job: IngestJob) -> int | None:
        """1-based place in line for a queued job (the running one is not counted)."""
        if job.state is not JobState.QUEUED:
            return None
        queued = [j for j in self.jobs() if j.state is JobState.QUEUED]
        return queued.index(job) + 1

    async def drain(self) -> None:
        """Waits until every submitted job has been taken and finished (tests, shutdown scripts)."""
        await self._pending.join()

    async def _run(self) -> None:
        while True:
            job_id = await self._pending.get()
            try:
                job = self._jobs.get(job_id)
                if job and job.state is JobState.QUEUED:
                    await self._process(job)
            finally:
                self._pending.task_done()

    async def _process(self, job: IngestJob) -> None:
        job.state, job.started_at = JobState.RUNNING, time.time()
        job.outcome = IngestOutcome(path=job.path, status=IngestStatus.FAILED)
        try:
            await self._ingest.ingest_one(Path(job.path), job.outcome)
        except Exception as e:  # noqa: BLE001 — ingest_one already isolates errors; this guards the worker itself
            job.outcome.error_type, job.outcome.error = type(e).__name__, str(e)
            log.exception("ingest.job.crashed", extra={"event": "ingest.job.crashed", "job_id": job.id})
        job.state = JobState(job.outcome.status.value)
        job.finished_at = time.time()
        self._trim()

    def _trim(self) -> None:
        finished = [j for j in self.jobs() if j.state in FINISHED]
        for j in finished[: max(0, len(finished) - self._keep)]:
            del self._jobs[j.id]
