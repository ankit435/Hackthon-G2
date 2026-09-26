"""Environment check for SETUP.md step 7. Exits non-zero on the first hard failure.

Run from the repo root inside the venv:  python scripts/verify_env.py
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
EMBEDDING_DIM = 1024  # must equal vector(1024) in db/schema.sql (BAAI/bge-m3)
failures = []


def check(name, fn):
    try:
        print(f"[ok]   {name}: {fn()}")
    except Exception as e:
        failures.append(name)
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")


def python_version():
    assert sys.version_info[:2] == (3, 12), f"need Python 3.12, got {sys.version.split()[0]}"
    assert sys.prefix != sys.base_prefix, "not running inside a virtual environment"
    return sys.version.split()[0]


def ffmpeg():
    path = shutil.which("ffmpeg")
    assert path, "ffmpeg not on PATH"
    return path


def audio_decode():
    from torchcodec.decoders import AudioDecoder
    samples = AudioDecoder(str(ROOT / "dataset/audio_01_rate_limiter.wav")).get_all_samples()
    return f"{samples.data.shape[1] / samples.sample_rate:.2f}s @ {samples.sample_rate} Hz"


def model_libs():
    import ctranslate2
    import faster_whisper
    import pyannote.audio
    return f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, pyannote.audio {pyannote.audio.__version__}"


def embedder():
    from sentence_transformers import SentenceTransformer

    from api.settings import load_settings
    settings = load_settings()  # loads the *configured* model, not a hard-coded one (M4)
    model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
    dim = model.get_embedding_dimension()
    assert dim == EMBEDDING_DIM, f"embedding dim {dim} != schema {EMBEDDING_DIM}"
    return f"model={settings.embedding_model} dim={dim}, max_seq_length={model.max_seq_length}"


def env_file_value(key):
    env = ROOT / ".env"
    if not env.exists():
        return None
    lines = (l.split("=", 1) for l in env.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
    return {k.strip(): v.strip() for k, v in lines}.get(key)


def hf_token():
    # Presence only; gated-repo access is verified when the diarization pipeline first loads.
    token = os.environ.get("HF_TOKEN") or env_file_value("HF_TOKEN")
    assert token and not token.startswith("hf_xxx"), "HF_TOKEN not set (env or .env)"
    return "set"


check("python", python_version)
check("ffmpeg", ffmpeg)
check("audio decode (torchcodec)", audio_decode)
check("model libraries", model_libs)
check("embedder", embedder)
check("HF_TOKEN", hf_token)

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
