"""Build the translated evaluation dataset (PLAN.md §7B, Task 17 M8) from the committed translations.

Inputs (all committed, reviewable):
  dataset/reference_corrected/<audio_id>.json          English source, D1-corrected
  dataset/multilingual/translations/<lang>/<audio_id>.txt   one line per segment, line i == segment i
  dataset/multilingual/translations/qa.json            translated question + answer per golden QA item
  dataset/all.json                                     English QA (supporting_context resolves the evidence)

Outputs:
  dataset/multilingual/<lang>/<audio_id>_<lang>.json    segment-aligned reference; times are filled by
                                                        scripts/synthesize_multilingual.py
  dataset/multilingual/<lang>/qa.json                   same-language QA with evidence by segment index
  dataset/multilingual/manifest.json                    every translated file, its language and status

Stdlib only. Deterministic: re-running on the same inputs gives byte-identical outputs, and it
preserves any timing already written by the synthesis step. Fails loudly on any alignment problem.
Run from the repo root:  python scripts/build_multilingual_dataset.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
ML = DATASET / "multilingual"
LANGS = ("es", "hi", "zh")
# One distinctive script check per language, so an English line left untranslated is caught.
SCRIPT = {"es": None, "hi": re.compile(r"[ऀ-ॿ]"), "zh": re.compile(r"[一-鿿]")}
TOPICS = {
    "audio_01_rate_limiter": {"es": "Limitador de tasa distribuido", "hi": "डिस्ट्रिब्यूटेड रेट लिमिटर", "zh": "分布式限流器"},
    "audio_02_url_shortener": {"es": "Acortador de URL a gran escala", "hi": "बड़े स्केल पर URL शॉर्टनर", "zh": "大规模短链接服务"},
    "audio_03_chat_system": {"es": "Sistema de chat y mensajería en tiempo real", "hi": "रियल टाइम चैट और मैसेजिंग सिस्टम", "zh": "实时聊天与消息系统"},
    "audio_04_news_feed": {"es": "Ranking y fan out de un feed social de noticias", "hi": "सोशल न्यूज़ फ़ीड की रैंकिंग और फ़ैन आउट", "zh": "社交信息流的排序与扩散"},
    "audio_05_payment_idempotency": {"es": "Procesamiento de pagos e idempotencia", "hi": "पेमेंट प्रोसेसिंग और आइडेम्पोटेंसी", "zh": "支付处理与幂等性"},
    "audio_06_video_streaming": {"es": "Pipeline de streaming y entrega de vídeo", "hi": "वीडियो स्ट्रीमिंग और डिलीवरी पाइपलाइन", "zh": "视频流媒体与分发流水线"},
}
TRANSLATION_NOTE = ("LLM-drafted by the coding agent (session 2), segment-aligned; "
                    "PENDING human verification (PLAN.md §7B). Proper nouns (Redis, Lua, WebSocket, "
                    "RTMP, Feistel, Saga, API, URL) are kept in Latin script in every language.")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(msg: str) -> None:
    sys.exit(f"build_multilingual_dataset: {msg}")


def golden_ids() -> list[str]:
    return [f["audio_id"] for f in json.loads((DATASET / "golden_set.json").read_text())["files"]]


def read_lines(path: Path, lang: str, expected: list[str]) -> list[str]:
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != len(expected):
        fail(f"{path}: {len(lines)} lines, source has {len(expected)} segments")
    for i, (line, src) in enumerate(zip(lines, expected)):
        if not line.strip() or line != line.strip():
            fail(f"{path}:{i + 1}: empty line or surrounding whitespace")
        if line == src:
            fail(f"{path}:{i + 1}: identical to the English source (untranslated)")
        if SCRIPT[lang] and not SCRIPT[lang].search(line):
            fail(f"{path}:{i + 1}: no {lang} script characters (untranslated?)")
    return lines


def evidence_indices(item: dict, segments: list[dict]) -> list[int]:
    """Resolve each English supporting quote to its unique segment (PROVENANCE.md D2: 134/134 unique)."""
    found = []
    for quote in item["supporting_context"]:
        hits = [i for i, s in enumerate(segments) if quote.lower() in s["text"].lower()]
        if len(hits) != 1:
            fail(f"{item['qa_id']}: quote resolves to {len(hits)} segments: {quote[:60]!r}")
        found.append(hits[0])
    return sorted(set(found))


def existing(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> int:
    ids = golden_ids()
    qa_en = [q for q in json.loads((DATASET / "all.json").read_text()) if q["audio_id"] in ids]
    qa_tr = json.loads((ML / "translations" / "qa.json").read_text(encoding="utf-8"))
    if set(qa_tr) != {q["qa_id"] for q in qa_en}:
        fail("translations/qa.json does not cover exactly the golden QA items")

    manifest = {"name": "Multilingual evaluation set: translations of golden files 01-06",
                "decision": "PLAN.md §7B Q21b: es, hi, zh translations of golden 01-06, segment-aligned",
                "translation": TRANSLATION_NOTE, "files": []}
    for lang in LANGS:
        out_dir = ML / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        refs = {}
        for audio_id in ids:
            src_path = DATASET / "reference_corrected" / f"{audio_id}.json"
            src = json.loads(src_path.read_text())
            tr_path = ML / "translations" / lang / f"{audio_id}.txt"
            lines = read_lines(tr_path, lang, [s["text"] for s in src["segments"]])
            out_path = out_dir / f"{audio_id}_{lang}.json"
            prev = existing(out_path)
            # Keep timings from a previous synthesis only if the text it was synthesised from is unchanged.
            keep = prev and prev.get("synthesis") and prev["translation"]["translation_sha256"] == sha256(tr_path)
            segments = [{"index": i, "speaker": s["speaker"], "text": t,
                         "start": prev["segments"][i]["start"] if keep else None,
                         "end": prev["segments"][i]["end"] if keep else None}
                        for i, (s, t) in enumerate(zip(src["segments"], lines))]
            ref = {"dataset": "Synthetic Two-Speaker Golden Audio Dataset — multilingual translations",
                   "audio_id": f"{audio_id}_{lang}", "source_audio_id": audio_id, "language": lang,
                   "topic": TOPICS[audio_id][lang], "source_topic": src["topic"],
                   "duration_seconds": prev["duration_seconds"] if keep else None,
                   "speakers": src["speakers"], "segments": segments,
                   "translation": {"method": TRANSLATION_NOTE, "source_reference": f"reference_corrected/{audio_id}.json",
                                   "source_reference_sha256": sha256(src_path),
                                   "translation_file": f"multilingual/translations/{lang}/{audio_id}.txt",
                                   "translation_sha256": sha256(tr_path)},
                   "synthesis": prev["synthesis"] if keep else None}
            out_path.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            refs[audio_id] = (src, segments)
            manifest["files"].append({"audio_id": ref["audio_id"], "source_audio_id": audio_id, "language": lang,
                                      "audio": f"{lang}/{audio_id}_{lang}.wav", "reference": f"{lang}/{audio_id}_{lang}.json",
                                      "segments": len(segments),
                                      "duration_seconds": ref["duration_seconds"],
                                      "sha256": ref["synthesis"]["wav_sha256"] if keep else None,
                                      "status": "synthesized" if keep else "pending_synthesis"})

        qa_out = []
        for item in qa_en:
            src, segments = refs[item["audio_id"]]
            idx = evidence_indices(item, src["segments"])
            tr = qa_tr[item["qa_id"]][lang]
            qa_out.append({"qa_id": f"{item['qa_id']}_{lang}", "source_qa_id": item["qa_id"],
                           "audio_id": f"{item['audio_id']}_{lang}", "language": lang,
                           "question": tr["question"], "ground_truth_answer": tr["answer"],
                           "question_en": item["question"],
                           "question_type": item["question_type"], "difficulty": item["difficulty"],
                           "evidence_segment_indices": idx,
                           "evidence_speakers": sorted({segments[i]["speaker"] for i in idx}),
                           "supporting_context": [segments[i]["text"] for i in idx]})
        (out_dir / "qa.json").write_text(json.dumps(qa_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (ML / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending = sum(f["status"] == "pending_synthesis" for f in manifest["files"])
    print(f"built {len(manifest['files'])} references + {len(LANGS)} QA files; {pending} awaiting synthesis")
    return 0


if __name__ == "__main__":
    sys.exit(main())
