"""Run the labeled query set against the live index and print/save the metrics report.

Run from the repo root inside the venv:  python scripts/evaluate.py [LANGUAGE]
Writes logs/eval-<language>-<timestamp>.json. Reports only; pytest (tests/eval) owns pass/fail.
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from api.container import build_evaluation_service  # noqa: E402
from api.settings import load_settings  # noqa: E402
from infra.dataset import corrected_references, golden_files, query_set  # noqa: E402


async def main(language: str) -> int:
    logging.basicConfig(level=logging.ERROR)  # per-request search logs would drown the report
    settings = load_settings()
    queries, meta = query_set(language)
    files = golden_files()
    report = await build_evaluation_service(settings).run(
        queries, corrected_references(), {f["audio_id"]: f["sha256"] for f in files}, {f["audio"]: f["audio_id"] for f in files})
    report["query_set"] = meta
    report["embedding_model"] = settings.embedding_model
    out = ROOT / "logs" / f"eval-{language}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, indent=1, default=str))
    print(f"\nfull report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "en")))
