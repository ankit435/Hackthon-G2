"""Background ingest queue: uploads return at once and a worker ingests the files one by one.

Jobs are stored through a JobRepository (Postgres in production), so the queue survives restarts:
queued jobs are picked up again when the server comes back, and a job that was running when its
process died is re-queued once its heartbeat goes stale (or failed after `max_attempts`, so a file
that crashes the worker cannot loop forever).

One worker per process on purpose: transcription, diarization and embedding each saturate the
CPU/GPU, so running files in parallel only makes every file slower. Several processes may still
share the queue safely; the repository's claim is atomic.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from pathlib import Path
from uuid import UUID

from application.ingest import IngestOutcome, IngestService, IngestStatus
from domain.models import IngestJob, JobState
from domain.ports import JobRepository

log = logging.getLogger(__name__)


def outcome_dict(outcome: IngestOutcome) -> dict:
    d = dataclasses.asdict(outcome)
    d["status"] = outcome.status.value
    return d


class IngestQueue:
    def __init__(self, ingest: IngestService, jobs: JobRepository, *, keep_finished: int = 200,
                 poll_seconds: float = 1.0, heartbeat_seconds: float = 2.0, stale_seconds: float = 60.0,
                 max_attempts: int = 3) -> None:
        self._ingest, self._jobs = ingest, jobs
        self._keep, self._poll, self._beat = keep_finished, poll_seconds, heartbeat_seconds
        self._stale, self._max_attempts = stale_seconds, max_attempts
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="ingest-queue")

    async def stop(self) -> None:
        """Stops the worker. A job cut off mid-run stays `running` and is re-queued once its heartbeat is stale."""
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def submit(self, path: Path, file_name: str | None = None) -> IngestJob:
        job = await self._jobs.add(IngestJob(file_name=file_name or path.name, path=str(path)))
        log.info("ingest.job.queued", extra={"event": "ingest.job.queued", "job_id": str(job.id), "file": job.path})
        self._wake.set()
        return job

    async def record_failure(self, file_name: str, outcome: IngestOutcome) -> IngestJob:
        """A file rejected before it could be queued (e.g. a bad upload) still shows up in the job list."""
        return await self._jobs.add(IngestJob(file_name=file_name, path=outcome.path, state=JobState.FAILED,
                                              stage=outcome.stage, outcome=outcome_dict(outcome)))

    async def cancel(self, job_id: UUID) -> IngestJob | None:
        return await self._jobs.cancel(job_id)

    async def get(self, job_id: UUID) -> IngestJob | None:
        return await self._jobs.get(job_id)

    async def jobs(self) -> list[IngestJob]:
        return await self._jobs.list_jobs(self._keep)

    async def run_pending(self) -> int:
        """Processes queued jobs until none is left; returns how many ran (the worker loop, tests, scripts)."""
        ran = 0
        while (job := await self._jobs.claim_next()) is not None:
            await self._process(job)
            ran += 1
        return ran

    async def _run(self) -> None:
        while True:
            try:
                recovered = await self._jobs.recover_stale(self._stale, self._max_attempts)
                if recovered:
                    log.warning("ingest.job.recovered", extra={"event": "ingest.job.recovered", "jobs": recovered})
                await self.run_pending()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — e.g. the DB is briefly down: log and keep the worker alive
                log.exception("ingest.queue.error", extra={"event": "ingest.queue.error"})
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._poll)

    async def _process(self, job: IngestJob) -> None:
        outcome = IngestOutcome(path=job.path, status=IngestStatus.FAILED)
        run = asyncio.create_task(self._ingest.ingest_one(Path(job.path), outcome))
        # While the file runs, persist its live stage as soon as it changes, and refresh the heartbeat that
        # tells other processes this one is alive.
        loop = asyncio.get_running_loop()
        written, last_write = None, loop.time()
        try:
            while not run.done():
                await asyncio.wait({run}, timeout=min(0.5, self._beat))
                if not run.done() and (outcome.stage != written or loop.time() - last_write >= self._beat):
                    with contextlib.suppress(Exception):
                        await self._jobs.heartbeat(job.id, outcome.stage)
                    written, last_write = outcome.stage, loop.time()
        except asyncio.CancelledError:
            run.cancel()  # shutting down: the job stays `running` and is recovered once its heartbeat is stale
            raise
        try:
            run.result()
        except Exception as e:  # noqa: BLE001 — ingest_one already isolates errors; this guards the worker itself
            outcome.error_type, outcome.error = type(e).__name__, str(e)
            log.exception("ingest.job.crashed", extra={"event": "ingest.job.crashed", "job_id": str(job.id)})
        await self._jobs.finish(job.id, JobState(outcome.status.value), outcome_dict(outcome))
