"""Ingest audio files. With no arguments, ingests the golden set listed in dataset/golden_set.json.

Run from the repo root inside the venv:  python scripts/ingest.py [FILE ...]
Structured JSON logs go to stderr; a per-file outcome table goes to stdout. Exit 1 if any file failed.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from api.container import build_ingest_service, configure_logging  # noqa: E402
from api.settings import load_settings  # noqa: E402
from application.ingest import IngestStatus  # noqa: E402


def golden_paths() -> list[Path]:
    manifest = json.loads((ROOT / "dataset" / "golden_set.json").read_text())
    return [ROOT / "dataset" / f["audio"] for f in manifest["files"]]


async def main(argv: list[str]) -> int:
    settings = load_settings()
    configure_logging(settings.log_level)
    paths = [Path(a) for a in argv] or golden_paths()
    outcomes = await build_ingest_service(settings).ingest(paths)
    for o in outcomes:
        stages = " ".join(f"{k}={v:.1f}s" for k, v in o.stage_seconds.items())
        detail = f"{o.chunk_count} chunks {o.chunking} {stages}" if o.status is IngestStatus.INGESTED \
            else f"stage={o.stage} {o.error_type}: {o.error}" if o.status is IngestStatus.FAILED else "already ingested"
        print(f"{o.status.value:<17} {Path(o.path).name:<34} {detail}")
    return 1 if any(o.status is IngestStatus.FAILED for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
