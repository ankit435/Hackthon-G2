"""Synthesise the translated two-speaker audio (PLAN.md §7B, Task 17 M8). DEV-ONLY: never imported by src/.

Reads   dataset/multilingual/<lang>/<audio_id>_<lang>.json   (built by scripts/build_multilingual_dataset.py)
Writes  dataset/multilingual/<lang>/<audio_id>_<lang>.wav    mono 16-bit PCM, 24 kHz (Kokoro's native rate)
        and fills in each reference's exact segment start/end, duration and a `synthesis` block,
        then re-runs the builder so manifest.json gets the WAV sha256 and status.

Timing is exact by construction: segment i starts at the sample where its audio was placed, and
segments are separated by GAP_SECONDS of digital silence. No detection, no drift (cf. defect D1).

Setup (inside .venv, once):
    pip install -r requirements-dev.txt          # pins kokoro + misaki[zh]
    brew install espeak-ng                        # macOS; Linux: apt install espeak-ng (es/hi phonemes)
Run from the repo root:
    python scripts/synthesize_multilingual.py                 # all 18 files
    python scripts/synthesize_multilingual.py --lang hi       # one language
    python scripts/synthesize_multilingual.py --force         # re-synthesise existing files
The first run downloads Kokoro-82M (~330 MB) and six voice files from Hugging Face (not gated).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ML = ROOT / "dataset" / "multilingual"
REPO_ID = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24_000
GAP_SECONDS = 0.25
SPEED = 1.0
# Kokoro language codes and two distinct voices per language (one female, one male).
# SPEAKER_00 -> first voice, SPEAKER_01 -> second, in every file of that language.
LANG = {
    "es": {"code": "e", "voices": {"SPEAKER_00": "ef_dora", "SPEAKER_01": "em_alex"}},
    "hi": {"code": "h", "voices": {"SPEAKER_00": "hf_alpha", "SPEAKER_01": "hm_omega"}},
    "zh": {"code": "z", "voices": {"SPEAKER_00": "zf_xiaobei", "SPEAKER_01": "zm_yunjian"}},
}
# Kokoro's espeak path (es/hi) does not chunk long text: feed one sentence per line so nothing is truncated.
_SENTENCE = re.compile(r"(?<=[.!?¿¡।॥])\s+|(?<=[。！？])")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthesize_segment(pipeline, text: str, voice: str):
    import numpy as np

    lines = "\n".join(p.strip() for p in _SENTENCE.split(text) if p.strip())
    parts = [r.audio.detach().cpu().numpy() for r in pipeline(lines, voice=voice, speed=SPEED, split_pattern=r"\n+")
             if r.audio is not None]
    if not parts:
        raise RuntimeError(f"no audio produced for: {text[:60]!r}")
    return np.concatenate(parts)


def synthesize_file(ref_path: Path, pipelines: dict, force: bool) -> str:
    import numpy as np

    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    wav_path = ref_path.with_suffix(".wav")
    if ref.get("synthesis") and wav_path.exists() and not force:
        return f"skip    {wav_path.name} (already synthesised; --force to redo)"
    lang = ref["language"]
    pipeline, voices = pipelines[lang], LANG[lang]["voices"]
    gap = np.zeros(int(round(GAP_SECONDS * SAMPLE_RATE)), dtype=np.float32)
    chunks, cursor = [], 0
    for i, seg in enumerate(ref["segments"]):
        if i:
            chunks.append(gap)
            cursor += len(gap)
        audio = synthesize_segment(pipeline, seg["text"], voices[seg["speaker"]]).astype(np.float32)
        seg["start"] = round(cursor / SAMPLE_RATE, 3)
        cursor += len(audio)
        seg["end"] = round(cursor / SAMPLE_RATE, 3)
        chunks.append(audio)
    samples = np.concatenate(chunks)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    import kokoro
    ref["duration_seconds"] = round(len(samples) / SAMPLE_RATE, 3)
    ref["synthesis"] = {"engine": "kokoro", "engine_version": getattr(kokoro, "__version__", "unknown"),
                        "model_repo": REPO_ID, "lang_code": LANG[lang]["code"], "voices": voices,
                        "speed": SPEED, "gap_seconds": GAP_SECONDS, "sample_rate": SAMPLE_RATE,
                        "format": "wav pcm_s16le mono", "timing": "exact: sample offsets of each synthesised segment",
                        "wav_sha256": sha256(wav_path)}
    ref_path.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"wrote   {wav_path.name}  {ref['duration_seconds']:.1f}s  {len(ref['segments'])} segments"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", choices=sorted(LANG), action="append", help="limit to these languages")
    ap.add_argument("--force", action="store_true", help="re-synthesise files that already have audio")
    args = ap.parse_args()
    langs = args.lang or sorted(LANG)

    try:
        from kokoro import KPipeline
    except ImportError:
        sys.exit("kokoro is not installed: pip install -r requirements-dev.txt (inside .venv)")
    pipelines = {}
    for lang in langs:
        pipelines[lang] = KPipeline(lang_code=LANG[lang]["code"], repo_id=REPO_ID)
        for voice in LANG[lang]["voices"].values():  # fail loudly now, not halfway through a file
            pipelines[lang].load_voice(voice)

    for lang in langs:
        for ref_path in sorted((ML / lang).glob("*_" + lang + ".json")):
            print(synthesize_file(ref_path, pipelines, args.force), flush=True)

    # The builder copies timings + sha256 into manifest.json (it keeps synthesis only while the text is unchanged).
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_multilingual_dataset.py")], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
