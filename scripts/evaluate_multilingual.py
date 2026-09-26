"""Task 17 M8: per-language evaluation. Requires the language's files already ingested
(python scripts/ingest.py dataset/multilingual/<lang>/*.wav).

Run from the repo root inside the venv:  python scripts/evaluate_multilingual.py <es|hi|zh> [...]
Writes logs/eval-<language>-<timestamp>.json, same shape as scripts/evaluate.py's report.
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
from infra.dataset import multilingual_files, multilingual_query_set, multilingual_references  # noqa: E402


async def run_one(language: str, settings) -> dict:
    files = multilingual_files(language)
    queries = multilingual_query_set(language)
    report = await build_evaluation_service(settings).run(
        queries, multilingual_references(language),
        {f["audio_id"]: f["sha256"] for f in files}, {Path(f["audio"]).name: f["audio_id"] for f in files})
    report["language"] = language
    report["embedding_model"] = settings.embedding_model
    return report


async def main(languages: list[str]) -> int:
    logging.basicConfig(level=logging.ERROR)
    settings = load_settings()
    exit_code = 0
    for language in languages:
        try:
            report = await run_one(language, settings)
        except ValueError as e:
            print(f"{language}: SKIPPED — {e}")
            exit_code = 1
            continue
        out = ROOT / "logs" / f"eval-{language}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report, indent=1, default=str))
        f = report["fused"]
        print(f"{language}: overall r@5={f['overall']['recall@5']:.4f} r@10={f['overall']['recall@10']:.4f} "
              f"speaker={report['speaker_accuracy']['accuracy']} p95={report['latency_ms']['p95']}ms -> {out.relative_to(ROOT)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or ["es", "hi", "zh"])))
