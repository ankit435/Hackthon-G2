"""Ingest queue: one by one in order, live stage, cancel, failure isolation, and recovery after a restart."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application.ingest import IngestOutcome, IngestStatus
from application.jobs import IngestQueue
from domain.models import JobState
from tests.unit.fake_jobs import InMemoryJobRepository


class FakeIngest:
    def __init__(self):
        self.running = 0
        self.max_running = 0
        self.order: list[str] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def ingest_one(self, path: Path, outcome: IngestOutcome) -> IngestOutcome:
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self.order.append(path.name)
        outcome.stage = "transcribe"
        await self.gate.wait()
        await asyncio.sleep(0)
        self.running -= 1
        if path.name.startswith("bad"):
            outcome.error = "boom"
            raise RuntimeError("worker must survive this")
        outcome.status, outcome.stage, outcome.chunk_count = IngestStatus.INGESTED, None, 3
        return outcome


async def _until(cond, tries=200):
    for _ in range(tries):
        if await cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


@pytest.mark.asyncio
async def test_jobs_run_one_by_one_in_order_and_a_failure_does_not_stop_the_queue():
    ingest, repo = FakeIngest(), InMemoryJobRepository()
    queue = IngestQueue(ingest, repo)  # type: ignore[arg-type]
    jobs = [await queue.submit(Path(n)) for n in ("a.wav", "bad.wav", "c.wav")]
    assert [j.position for j in jobs] == [1, 2, 3]
    assert await queue.run_pending() == 3
    assert ingest.max_running == 1
    assert ingest.order == ["a.wav", "bad.wav", "c.wav"]
    done = [await queue.get(j.id) for j in jobs]
    assert [j.state for j in done] == [JobState.INGESTED, JobState.FAILED, JobState.INGESTED]
    assert done[1].outcome["error_type"] == "RuntimeError" and done[0].outcome["chunk_count"] == 3
    assert done[0].outcome["status"] == "ingested"  # JSON-ready, not an Enum
    assert all(j.started_at and j.finished_at and j.attempts == 1 for j in done)


@pytest.mark.asyncio
async def test_worker_persists_the_live_stage_and_cancel_skips_a_queued_job():
    ingest, repo = FakeIngest(), InMemoryJobRepository()
    ingest.gate.clear()
    queue = IngestQueue(ingest, repo, poll_seconds=0.01, heartbeat_seconds=0.02)  # type: ignore[arg-type]
    a, b, c = [await queue.submit(Path(n)) for n in ("a.wav", "b.wav", "c.wav")]
    queue.start()
    await _until(lambda: _stage_is(queue, a.id, "transcribe"))
    assert [(await queue.get(j.id)).position for j in (b, c)] == [1, 2]
    assert (await queue.cancel(b.id)).state is JobState.CANCELLED
    assert (await queue.cancel(a.id)).state is JobState.RUNNING  # a running job is not interrupted
    assert (await queue.get(c.id)).position == 1
    ingest.gate.set()
    await _until(lambda: _state_is(queue, c.id, JobState.INGESTED))
    await queue.stop()
    assert ingest.order == ["a.wav", "c.wav"]
    assert repo.stages[0] == "transcribe"


async def _stage_is(queue, job_id, stage):
    return (await queue.get(job_id)).stage == stage


async def _state_is(queue, job_id, state):
    return (await queue.get(job_id)).state is state


@pytest.mark.asyncio
async def test_a_restart_picks_up_queued_jobs_and_recovers_a_job_whose_worker_died():
    repo = InMemoryJobRepository()
    first = IngestQueue(FakeIngest(), repo)  # type: ignore[arg-type]
    crashed = await first.submit(Path("a.wav"))
    waiting = await first.submit(Path("b.wav"))
    await repo.claim_next()  # the old process took a.wav, then died without finishing it
    repo.heartbeats[crashed.id] = datetime.now(timezone.utc) - timedelta(minutes=5)

    ingest = FakeIngest()
    second = IngestQueue(ingest, repo, poll_seconds=0.01, stale_seconds=60)  # type: ignore[arg-type]
    second.start()
    await _until(lambda: _state_is(second, waiting.id, JobState.INGESTED))
    await second.stop()
    assert sorted(ingest.order) == ["a.wav", "b.wav"]
    a = await second.get(crashed.id)
    assert a.state is JobState.INGESTED and a.attempts == 2


@pytest.mark.asyncio
async def test_a_job_that_keeps_killing_the_worker_is_failed_not_retried_forever():
    repo = InMemoryJobRepository()
    queue = IngestQueue(FakeIngest(), repo, max_attempts=2)  # type: ignore[arg-type]
    job = await queue.submit(Path("poison.wav"))
    for _ in range(2):
        await repo.claim_next()
        repo.heartbeats[job.id] = datetime.now(timezone.utc) - timedelta(minutes=5)
        await repo.recover_stale(60, 2)
    failed = await queue.get(job.id)
    assert failed.state is JobState.FAILED and failed.outcome["error_type"] == "WorkerLost"


@pytest.mark.asyncio
async def test_rejected_uploads_are_listed_as_failed_jobs():
    repo = InMemoryJobRepository()
    queue = IngestQueue(FakeIngest(), repo, keep_finished=2)  # type: ignore[arg-type]
    for i in range(3):
        await queue.record_failure(f"x{i}.txt", IngestOutcome(path=f"x{i}.txt", status=IngestStatus.FAILED, stage="upload"))
    listed = await queue.jobs()
    assert [j.file_name for j in listed] == ["x1.txt", "x2.txt"]  # newest finished jobs only
    assert all(j.state is JobState.FAILED and j.outcome["stage"] == "upload" for j in listed)
