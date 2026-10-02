"""PostgresJobRepository against a throwaway database (the queue's claim would otherwise take real jobs)."""
import asyncio
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from api.settings import load_settings
from domain.models import IngestJob, JobState
from infra.postgres import PostgresJobRepository

BASE_URL = load_settings().database_url
SCHEMA = (Path(__file__).resolve().parents[2] / "db" / "schema.sql").read_text()


@pytest.fixture
def repo():
    name = f"{conninfo_to_dict(BASE_URL)['dbname']}_jobs_{uuid.uuid4().hex[:8]}"
    admin_url = make_conninfo(BASE_URL, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(BASE_URL, dbname=name)
    with psycopg.connect(url) as conn:
        conn.execute(SCHEMA)
    yield PostgresJobRepository(url), url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def run(coro):
    return asyncio.run(coro)


def test_fifo_claim_positions_heartbeat_and_finish(repo):
    r, _ = repo
    a, b, c = [run(r.add(IngestJob(file_name=n, path=f"/u/{n}"))) for n in ("a.wav", "b.wav", "c.wav")]
    assert [j.position for j in (a, b, c)] == [1, 2, 3] and a.created_at is not None
    claimed = run(r.claim_next())
    assert claimed.id == a.id and claimed.state is JobState.RUNNING and claimed.attempts == 1
    run(r.heartbeat(a.id, "embed"))
    got = run(r.get(a.id))
    assert got.stage == "embed" and got.position is None and got.started_at is not None
    assert run(r.get(c.id)).position == 2
    run(r.finish(a.id, JobState.INGESTED, {"status": "ingested", "chunk_count": 7}))
    done = run(r.get(a.id))
    assert done.state is JobState.INGESTED and done.outcome["chunk_count"] == 7 and done.stage is None
    assert run(r.cancel(b.id)).state is JobState.CANCELLED
    assert run(r.claim_next()).id == c.id  # the cancelled job is skipped
    assert run(r.claim_next()) is None
    assert run(r.get(uuid.uuid4())) is None and run(r.cancel(uuid.uuid4())) is None


def test_concurrent_claims_never_hand_out_the_same_job(repo):
    r, _ = repo
    ids = {run(r.add(IngestJob(file_name=f"{i}.wav", path=f"/u/{i}.wav"))).id for i in range(6)}

    async def claim_all():
        return await asyncio.gather(*(r.claim_next() for _ in range(10)))

    claimed = [j.id for j in run(claim_all()) if j is not None]
    assert len(claimed) == len(set(claimed)) == 6 and set(claimed) == ids


def test_stale_running_jobs_are_requeued_then_failed_after_max_attempts(repo):
    r, url = repo
    job = run(r.add(IngestJob(file_name="a.wav", path="/u/a.wav")))
    run(r.claim_next())
    assert run(r.recover_stale(60, 2)) == 0  # fresh heartbeat: its worker is alive
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE ingest_job SET heartbeat_at = now() - interval '5 minutes'")
    assert run(r.recover_stale(60, 2)) == 1
    assert run(r.get(job.id)).state is JobState.QUEUED
    run(r.claim_next())
    run(r.heartbeat(job.id, "transcribe"))
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE ingest_job SET heartbeat_at = now() - interval '5 minutes'")
    assert run(r.recover_stale(60, 2)) == 1
    failed = run(r.get(job.id))
    assert failed.state is JobState.FAILED and failed.attempts == 2
    assert failed.outcome["error_type"] == "WorkerLost" and failed.outcome["stage"] == "transcribe"


def test_failed_upload_rows_and_list_limits(repo):
    r, _ = repo
    for i in range(3):
        run(r.add(IngestJob(file_name=f"x{i}.txt", path=f"x{i}.txt", state=JobState.FAILED, stage="upload",
                            outcome={"status": "failed", "stage": "upload"})))
    queued = run(r.add(IngestJob(file_name="q.wav", path="/u/q.wav")))
    listed = run(r.list_jobs(2))
    assert [j.file_name for j in listed] == ["x1.txt", "x2.txt", "q.wav"]  # newest 2 finished + every active job
    assert listed[0].finished_at is not None and listed[-1].id == queued.id and listed[-1].position == 1
