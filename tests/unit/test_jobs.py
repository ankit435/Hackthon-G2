"""Ingest queue: files are ingested one at a time, in order, with live stage, cancel and failure isolation."""
import asyncio
from pathlib import Path

import pytest

from application.ingest import IngestOutcome, IngestStatus
from application.jobs import IngestQueue, JobState


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


@pytest.mark.asyncio
async def test_jobs_run_one_by_one_in_order_and_a_failure_does_not_stop_the_queue():
    ingest = FakeIngest()
    queue = IngestQueue(ingest)  # type: ignore[arg-type]
    queue.start()
    jobs = [queue.submit(Path(n)) for n in ("a.wav", "bad.wav", "c.wav")]
    await queue.drain()
    await queue.stop()
    assert ingest.max_running == 1
    assert ingest.order == ["a.wav", "bad.wav", "c.wav"]
    assert [j.state for j in jobs] == [JobState.INGESTED, JobState.FAILED, JobState.INGESTED]
    assert jobs[1].outcome.error_type == "RuntimeError" and jobs[0].outcome.chunk_count == 3
    assert all(j.started_at and j.finished_at for j in jobs)


@pytest.mark.asyncio
async def test_live_stage_position_and_cancel():
    ingest = FakeIngest()
    ingest.gate.clear()
    queue = IngestQueue(ingest)  # type: ignore[arg-type]
    queue.start()
    a, b, c = (queue.submit(Path(n)) for n in ("a.wav", "b.wav", "c.wav"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert a.state is JobState.RUNNING and a.outcome.stage == "transcribe"
    assert (queue.position(a), queue.position(b), queue.position(c)) == (None, 1, 2)
    assert queue.cancel(b.id).state is JobState.CANCELLED
    assert queue.cancel(a.id).state is JobState.RUNNING  # a running job is not interrupted
    assert queue.position(c) == 1 and queue.cancel("nope") is None
    ingest.gate.set()
    await queue.drain()
    await queue.stop()
    assert ingest.order == ["a.wav", "c.wav"]
    assert [j.state for j in (a, b, c)] == [JobState.INGESTED, JobState.CANCELLED, JobState.INGESTED]


def test_finished_jobs_are_trimmed_but_failures_are_listed():
    queue = IngestQueue(FakeIngest(), keep_finished=2)  # type: ignore[arg-type]
    for i in range(4):
        queue.record_failure(f"x{i}.txt", IngestOutcome(path=f"x{i}.txt", status=IngestStatus.FAILED, stage="upload"))
    assert [j.file_name for j in queue.jobs()] == ["x2.txt", "x3.txt"]
