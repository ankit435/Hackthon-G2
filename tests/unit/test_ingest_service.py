"""IngestService with fakes: no models, no database (PLAN.md §5 dependency injection)."""
import asyncio
import logging
from pathlib import Path

import pytest

from application.chunking import ChunkingConfig
from application.ingest import IngestService, IngestStatus, sha256_file
from domain.errors import TranscriptionError
from domain.models import DecodedAudio, SpeakerTurn, Transcript, TranscriptSegment

CFG = ChunkingConfig(20, 45)


class FakeDecoder:
    def decode(self, path):
        return DecodedAudio(path=path, samples=[0.0] * 16000 * 30, sample_rate=16000)


class FakeTranscriber:
    def __init__(self, fail_on=(), language="es", probability=0.93):
        self.fail_on, self.language, self.probability = set(fail_on), language, probability

    def transcribe(self, audio):
        if audio.path.name in self.fail_on:
            raise TranscriptionError("boom", stage="transcribe", file=audio.path.name)
        return Transcript([TranscriptSegment(0, 5, " Hello there."), TranscriptSegment(5.2, 9, " General Kenobi."),
                           TranscriptSegment(9.1, 9.1, "  ")], self.language, self.probability)


class FakeDiarizer:
    def diarize(self, audio, num_speakers):
        assert num_speakers == 2
        return [SpeakerTurn(0, 5.1, "SPEAKER_00"), SpeakerTurn(5.1, 10, "SPEAKER_01")]


class FakeEmbedder:
    dimension, max_tokens = 3, 256

    def __init__(self):
        self.calls = 0

    def count_tokens(self, text):
        return len(text.split()) + 2

    async def embed(self, texts):
        self.calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeRepo:
    def __init__(self, existing=()):
        self.existing, self.saved = set(existing), []

    async def find_by_checksum(self, checksum):
        from domain.models import AudioFile
        return AudioFile("x.wav", "/x.wav", checksum, 30.0, "en", 1.0) if checksum in self.existing else None

    async def add_with_chunks(self, audio_file, chunks):
        self.saved.append((audio_file, list(chunks)))


@pytest.fixture
def wavs(tmp_path):
    paths = []
    for name in ("a.wav", "b.wav"):
        p = tmp_path / name
        p.write_bytes(name.encode())  # distinct content -> distinct checksums
        paths.append(p)
    return paths


def service(repo, transcriber=None, embedder=None):
    return IngestService(FakeDecoder(), transcriber or FakeTranscriber(), FakeDiarizer(),
                         embedder or FakeEmbedder(), repo, CFG)


def test_ingests_file_end_to_end_with_linked_chunks(wavs):
    repo, embedder = FakeRepo(), FakeEmbedder()
    [out] = asyncio.run(service(repo, embedder=embedder).ingest(wavs[:1]))
    assert out.status is IngestStatus.INGESTED and out.chunk_count == 2 and out.stage is None
    audio_file, chunks = repo.saved[0]
    assert audio_file.checksum == sha256_file(wavs[0]) and audio_file.duration_seconds == 30.0
    assert [(c.speaker, c.text, c.start_time, c.end_time) for c in chunks] == [
        ("SPEAKER_00", "Hello there.", 0, 5), ("SPEAKER_01", "General Kenobi.", 5.2, 9)]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert (chunks[0].prev_chunk_id, chunks[0].next_chunk_id) == (None, chunks[1].id)
    assert (chunks[1].prev_chunk_id, chunks[1].next_chunk_id) == (chunks[0].id, None)
    assert all(c.audio_file_id == audio_file.id and c.embedding == (1.0, 0.0, 0.0) for c in chunks)
    assert [c.token_count for c in chunks] == [4, 4] and chunks[0].char_count == len("Hello there.")
    assert embedder.calls == 1  # one batched call for all chunk texts (no long turns here)
    assert out.chunking["dropped_empty_segments"] == 1
    assert set(out.stage_seconds) == {"validate", "decode", "transcribe", "diarize", "align", "chunk", "embed", "persist"}
    # language detected by the transcriber reaches the outcome, the file record and every chunk
    assert (out.language, out.language_probability) == ("es", 0.93)
    assert (audio_file.language, audio_file.language_probability) == ("es", 0.93)
    assert {c.language for c in chunks} == {"es"}


def test_one_failure_does_not_abort_the_batch(wavs):
    repo = FakeRepo()
    outs = asyncio.run(service(repo, transcriber=FakeTranscriber(fail_on={"a.wav"})).ingest(wavs))
    assert [o.status for o in outs] == [IngestStatus.FAILED, IngestStatus.INGESTED]
    assert (outs[0].stage, outs[0].error_type) == ("transcribe", "TranscriptionError")
    assert len(repo.saved) == 1 and repo.saved[0][0].file_name == "b.wav"  # nothing persisted for the failure


def test_existing_checksum_is_skipped_without_running_models(wavs):
    repo = FakeRepo(existing={sha256_file(wavs[0])})
    [out] = asyncio.run(service(repo, transcriber=FakeTranscriber(fail_on={"a.wav"})).ingest(wavs[:1]))
    assert out.status is IngestStatus.SKIPPED_EXISTING and repo.saved == []  # transcriber never called


def test_missing_path_fails_at_validation(tmp_path):
    [out] = asyncio.run(service(FakeRepo()).ingest([tmp_path / "nope.wav"]))
    assert (out.status, out.stage, out.error_type) == (IngestStatus.FAILED, "validate", "InvalidInputError")


def test_unexpected_exception_is_isolated_and_recorded(wavs):
    class Exploding(FakeRepo):
        async def add_with_chunks(self, audio_file, chunks):
            raise RuntimeError("disk on fire")

    outs = asyncio.run(service(Exploding()).ingest(wavs))
    assert all(o.status is IngestStatus.FAILED and o.stage == "persist" and o.error_type == "RuntimeError" for o in outs)


def test_oversized_chunk_logs_truncation_warning(wavs, caplog):
    class TinyWindow(FakeEmbedder):
        max_tokens = 3

    asyncio.run(service(FakeRepo(), embedder=TinyWindow()).ingest(wavs[:1]))
    assert any(getattr(r, "event", "") == "ingest.chunk.truncated" for r in caplog.records)


def test_low_confidence_language_is_logged_and_kept(wavs, caplog):
    repo = FakeRepo()
    [out] = asyncio.run(service(repo, transcriber=FakeTranscriber(language="hi", probability=0.31)).ingest(wavs[:1]))
    assert out.status is IngestStatus.INGESTED and out.language == "hi" and out.language_probability == 0.31
    warn = [r for r in caplog.records if getattr(r, "event", "") == "ingest.language.low_confidence"]
    assert len(warn) == 1 and warn[0].levelname == "WARNING" and warn[0].language == "hi"
    assert repo.saved[0][0].language == "hi"  # ingest proceeds; the doubt is recorded, not hidden


def test_confident_language_does_not_warn(wavs, caplog):
    asyncio.run(service(FakeRepo(), transcriber=FakeTranscriber(language="en", probability=0.99)).ingest(wavs[:1]))
    assert not [r for r in caplog.records if getattr(r, "event", "") == "ingest.language.low_confidence"]


def test_ingest_logs_per_file_and_batch_aggregation_events(wavs, caplog):
    with caplog.at_level(logging.INFO, logger="application.ingest"):
        outcomes = asyncio.run(service(FakeRepo()).ingest(wavs))
    per_file = [r for r in caplog.records if getattr(r, "event", "") == "ingest.file.end"]
    assert len(per_file) == len(outcomes)
    assert all(r.status == "ingested" and r.audio_file_id and r.chunks == 2 for r in per_file)
    assert all(r.duration_ms >= 0 and r.audio_seconds_per_wall_second is not None for r in per_file)
    [batch] = [r for r in caplog.records if getattr(r, "event", "") == "ingest.batch.end"]
    assert (batch.files, batch.ingested, batch.failed, batch.skipped_existing) == (2, 2, 0, 0)
    assert batch.duration_ms >= 0
