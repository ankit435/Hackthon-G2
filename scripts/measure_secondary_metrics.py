"""Task 9: Secondary metrics measurement script (PLAN.md §10.3 - §10.4).

Measures actual ingested transcription WER/CER vs ground truth reference.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from jiwer import cer, wer

from api.settings import load_settings
from infra.postgres import PostgresRepository

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]


def compute_wer_cer(reference_text: str, hypothesis_text: str) -> tuple[float, float]:
    """Computes Word Error Rate (WER) and Character Error Rate (CER) via jiwer."""
    w_error = float(wer(reference_text, hypothesis_text))
    c_error = float(cer(reference_text, hypothesis_text))
    return round(w_error, 4), round(c_error, 4)


async def main():
    print("Measuring secondary quality metrics on live database chunks...")
    settings = load_settings()
    repo = PostgresRepository(settings.database_url)

    manifest_path = REPO_ROOT / "dataset" / "golden_set.json"
    if not manifest_path.is_file():
        print("Manifest dataset/golden_set.json not found.")
        return

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    ref_dir = REPO_ROOT / "dataset" / "reference_corrected"
    wers, cers = [], []

    for item in manifest.get("files", []):
        checksum = item["sha256"]
        file_name = item["file_name"]
        audio_file = await repo.find_by_checksum(checksum)
        if audio_file is None:
            print(f"Skipping {file_name}: not found in database.")
            continue

        chunks = await repo.list_by_file(audio_file.id)
        hypothesis_text = " ".join(c.text.strip() for c in chunks if c.text)

        ref_json_path = ref_dir / f"{item['id']}_{item['file_name'].replace('.wav', '')}.json"
        if not ref_json_path.is_file():
            # Try alternate file naming pattern
            ref_matches = list(ref_dir.glob(f"{item['id']}*.json"))
            if ref_matches:
                ref_json_path = ref_matches[0]

        if ref_json_path.is_file():
            with ref_json_path.open("r", encoding="utf-8") as rf:
                ref_data = json.load(rf)
                reference_text = " ".join(seg["text"].strip() for seg in ref_data.get("segments", []))

            w, c = compute_wer_cer(reference_text, hypothesis_text)
            wers.append(w)
            cers.append(c)
            print(f"  {item['id']} ({file_name}): WER={w:.4f}, CER={c:.4f} (chunks={len(chunks)})")
        else:
            print(f"  {item['id']} ({file_name}): reference JSON not found.")

    if wers:
        avg_wer = round(sum(wers) / len(wers), 4)
        avg_cer = round(sum(cers) / len(cers), 4)
        print(f"\nOverall Macro-Averaged Transcription Error: WER={avg_wer:.4f}, CER={avg_cer:.4f}")
    else:
        print("\nNo ingested files matched reference set.")


if __name__ == "__main__":
    asyncio.run(main())
