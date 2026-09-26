"""Synthesise the translated two-speaker audio (PLAN.md §7B, Task 17 M8). DEV-ONLY: never imported by src/.

Reads   dataset/multilingual/<lang>/<audio_id>_<lang>.json   (built by scripts/build_multilingual_dataset.py)
Writes  dataset/multilingual/<lang>/<audio_id>_<lang>.wav    mono 16-bit PCM, 16 kHz
        and fills in each reference's exact segment start/end, duration and a `synthesis` block,
        then re-runs the builder so qa.json gets evidence_time_ranges and manifest.json the sha256.

Engine: Kokoro-82M v1.0 via kokoro-onnx (ONNX runtime, CPU, deterministic). The model files come from
the kokoro-onnx GitHub release (no Hugging Face), are cached in ~/.cache/kokoro-onnx and verified by
sha256. es/hi are phonemised by the espeak-ng bundled with kokoro-onnx; zh by misaki's Mandarin G2P,
with embedded English words (API, Redis, ...) phonemised by espeak-ng en-us so they are spoken.

Timing is exact by construction: every segment is synthesised separately, resampled 24 kHz -> 16 kHz
(the rate ingestion decodes to), and placed after GAP_SECONDS of digital silence. Segment i starts at
the sample where it was placed. No detection, no drift (cf. defect D1).

Setup (inside .venv, once):   pip install -r requirements-dev.txt
Run from the repo root:
    python scripts/synthesize_multilingual.py                 # all 18 files (~40 min on CPU)
    python scripts/synthesize_multilingual.py --lang hi       # one language
    python scripts/synthesize_multilingual.py --force         # re-synthesise existing files
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ML = ROOT / "dataset" / "multilingual"
CACHE = Path.home() / ".cache" / "kokoro-onnx"
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = {  # name -> sha256, so a changed upstream file fails loudly instead of changing the audio
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
MODEL_RATE = 24_000
SAMPLE_RATE = 16_000
GAP_SECONDS = 0.25
SPEED = 1.0
# espeak language per file language (None = misaki Mandarin G2P) and two distinct voices per language.
# SPEAKER_00 -> female voice, SPEAKER_01 -> male voice, in every file of that language.
LANG = {
    "es": {"espeak": "es", "voices": {"SPEAKER_00": "ef_dora", "SPEAKER_01": "em_alex"}},
    "hi": {"espeak": "hi", "voices": {"SPEAKER_00": "hf_alpha", "SPEAKER_01": "hm_omega"}},
    "zh": {"espeak": None, "voices": {"SPEAKER_00": "zf_xiaobei", "SPEAKER_01": "zm_yunjian"}},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_file(name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} ...", flush=True)
        urllib.request.urlretrieve(RELEASE + name, path)
    if sha256(path) != MODEL_FILES[name]:
        sys.exit(f"{path}: sha256 mismatch; delete it and re-run")
    return path


class Synthesizer:
    def __init__(self) -> None:
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(model_file("kokoro-v1.0.onnx")), str(model_file("voices-v1.0.bin")))
        available = set(self.kokoro.get_voices())
        missing = {v for cfg in LANG.values() for v in cfg["voices"].values()} - available
        if missing:
            sys.exit(f"voices not in the model: {sorted(missing)}")
        self._zh = None

    def _zh_phonemes(self, text: str) -> str:
        if self._zh is None:
            from misaki import zh

            self._zh = zh.ZHG2P()  # v1.0 model -> misaki's legacy path, which drops embedded English
        # So split it ourselves: Latin runs (API, Redis, WebSocket) -> espeak en-us, the rest -> misaki.
        parts = []
        for latin, other in re.findall(r"([A-Za-z][A-Za-z0-9' -]*[A-Za-z0-9]|[A-Za-z])|([^A-Za-z]+)", text):
            if latin:
                parts.append(self.kokoro.tokenizer.phonemize(latin, "en-us").strip())
            elif other.strip():
                parts.append(self._zh(other)[0])
        phonemes = " ".join(p for p in parts if p)
        dropped = {c for c in phonemes if c not in self.kokoro.tokenizer.vocab}
        if dropped:  # the tokenizer silently drops out-of-vocabulary symbols, i.e. unspoken text
            raise RuntimeError(f"phonemes outside the model vocabulary {sorted(dropped)} in {phonemes!r}")
        return phonemes

    def segment(self, text: str, lang: str, voice: str):
        import numpy as np
        import soxr

        if LANG[lang]["espeak"] is None:
            audio, rate = self.kokoro.create(self._zh_phonemes(text), voice=voice, speed=SPEED, is_phonemes=True)
        else:
            audio, rate = self.kokoro.create(text, voice=voice, speed=SPEED, lang=LANG[lang]["espeak"])
        if rate != MODEL_RATE or len(audio) == 0:
            raise RuntimeError(f"unexpected output ({rate} Hz, {len(audio)} samples) for {text[:60]!r}")
        return soxr.resample(np.asarray(audio, dtype=np.float32), MODEL_RATE, SAMPLE_RATE, quality="HQ")


def synthesize_file(ref_path: Path, synth: Synthesizer, force: bool) -> str:
    import numpy as np

    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    wav_path = ref_path.with_suffix(".wav")
    if ref.get("synthesis") and wav_path.exists() and not force:
        return f"skip    {wav_path.name} (already synthesised; --force to redo)"
    lang, voices = ref["language"], LANG[ref["language"]]["voices"]
    gap = np.zeros(int(round(GAP_SECONDS * SAMPLE_RATE)), dtype=np.float32)
    chunks, cursor = [], 0
    for i, seg in enumerate(ref["segments"]):
        if i:
            chunks.append(gap)
            cursor += len(gap)
        audio = synth.segment(seg["text"], lang, voices[seg["speaker"]])
        seg["start"] = round(cursor / SAMPLE_RATE, 3)
        cursor += len(audio)
        seg["end"] = round(cursor / SAMPLE_RATE, 3)
        chunks.append(audio)
    samples = np.concatenate(chunks)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).round().astype("<i2")
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    from importlib.metadata import version
    ref["duration_seconds"] = round(len(samples) / SAMPLE_RATE, 3)
    ref["synthesis"] = {"engine": "kokoro-onnx", "engine_version": version("kokoro-onnx"),
                        "model": "Kokoro-82M v1.0 (kokoro-v1.0.onnx)", "model_sha256": MODEL_FILES["kokoro-v1.0.onnx"],
                        "g2p": "misaki zh + espeak-ng en-us for English words" if lang == "zh"
                        else f"espeak-ng {LANG[lang]['espeak']}",
                        "voices": voices, "speed": SPEED, "gap_seconds": GAP_SECONDS,
                        "sample_rate": SAMPLE_RATE, "resampled_from": MODEL_RATE, "format": "wav pcm_s16le mono",
                        "timing": "exact: sample offsets of each synthesised segment",
                        "wav_sha256": sha256(wav_path)}
    ref_path.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"wrote   {wav_path.name}  {ref['duration_seconds']:.1f}s  {len(ref['segments'])} segments"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", choices=sorted(LANG), action="append", help="limit to these languages")
    ap.add_argument("--force", action="store_true", help="re-synthesise files that already have audio")
    args = ap.parse_args()
    try:
        synth = Synthesizer()
    except ImportError as e:
        sys.exit(f"{e.name} is not installed: pip install -r requirements-dev.txt (inside .venv)")
    for lang in args.lang or sorted(LANG):
        for ref_path in sorted((ML / lang).glob(f"*_{lang}.json")):
            print(synthesize_file(ref_path, synth, args.force), flush=True)
    # The builder copies timings into qa.json and sha256/status into manifest.json.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_multilingual_dataset.py")], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
