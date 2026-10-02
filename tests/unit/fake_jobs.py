"""In-memory JobRepository with the same semantics as PostgresJobRepository (tested against it in integration)."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import UUID

from domain.models import FINISHED_JOB_STATES, IngestJob, JobState


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, IngestJob] = {}
        self.heartbeats: dict[UUID, datetime] = {}
        self.stages: list[str | None] = []  # every stage written by heartbeat, in order

    def _out(self, job: IngestJob) -> IngestJob:
        queued = [j.id for j in self.rows.values() if j.state is JobState.QUEUED]
        return dataclasses.replace(job, position=queued.index(job.id) + 1 if job.id in queued else None)

    async def add(self, job: IngestJob) -> IngestJob:
        now = datetime.now(timezone.utc)
        job = dataclasses.replace(job, created_at=now)
        if job.state is not JobState.QUEUED:
            job.started_at = job.finished_at = now
        self.rows[job.id] = job
        return self._out(job)

    async def claim_next(self) -> IngestJob | None:
        job = next((j for j in self.rows.values() if j.state is JobState.QUEUED), None)
        if job:
            job.state, job.stage, job.attempts = JobState.RUNNING, None, job.attempts + 1
            job.started_at = datetime.now(timezone.utc)
            self.heartbeats[job.id] = job.started_at
        return self._out(job) if job else None

    async def heartbeat(self, job_id: UUID, stage: str | None) -> None:
        job = self.rows[job_id]
        if job.state is JobState.RUNNING:
            job.stage = stage
            self.stages.append(stage)
            self.heartbeats[job_id] = datetime.now(timezone.utc)

    async def finish(self, job_id: UUID, state: JobState, outcome: dict | None) -> None:
        job = self.rows[job_id]
        job.state, job.stage, job.outcome, job.finished_at = state, None, outcome, datetime.now(timezone.utc)

    async def cancel(self, job_id: UUID) -> IngestJob | None:
        job = self.rows.get(job_id)
        if job and job.state is JobState.QUEUED:
            job.state, job.finished_at = JobState.CANCELLED, datetime.now(timezone.utc)
        return self._out(job) if job else None

    async def get(self, job_id: UUID) -> IngestJob | None:
        job = self.rows.get(job_id)
        return self._out(job) if job else None

    async def list_jobs(self, finished_limit: int) -> list[IngestJob]:
        finished = [j for j in self.rows.values() if j.state in FINISHED_JOB_STATES][-finished_limit:] if finished_limit else []
        keep = {j.id for j in finished}
        return [self._out(j) for j in self.rows.values() if j.state not in FINISHED_JOB_STATES or j.id in keep]

    async def recover_stale(self, stale_seconds: float, max_attempts: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        changed = 0
        for job in self.rows.values():
            if job.state is JobState.RUNNING and self.heartbeats.get(job.id, cutoff) < cutoff:
                if job.attempts >= max_attempts:
                    job.state, job.finished_at = JobState.FAILED, datetime.now(timezone.utc)
                    job.outcome = {"status": "failed", "stage": job.stage, "error_type": "WorkerLost"}
                else:
                    job.state, job.stage, job.started_at = JobState.QUEUED, None, None
                changed += 1
        return changed
