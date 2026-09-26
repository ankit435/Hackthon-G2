"""Build dataset/queries/en.json (+ en.review.md for human verification) from en.source.json.

Keyword ground truth is COMPUTED, not hand-picked: every golden-set reference segment whose text
contains the phrase (case-insensitive, word boundaries, each word may take a plural s/es) is
evidence, in any file. Semantic evidence comes from the source (hand-picked or all.json).
Fails loudly on a phrase that matches nothing or an out-of-range segment index.

Run from the repo root:  python scripts/build_query_set.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
OUT = DATASET / "queries"


def phrase_regex(phrase: str) -> re.Pattern:
    words = [re.escape(w) + r"(?:s|es)?" for w in phrase.lower().split()]
    return re.compile(r"\b" + r"[\s-]+".join(words) + r"\b")


def main() -> int:
    source = json.loads((OUT / "en.source.json").read_text())
    golden = [f["audio_id"] for f in json.loads((DATASET / "golden_set.json").read_text())["files"]]
    refs = {a: json.loads((DATASET / "reference_corrected" / f"{a}.json").read_text())["segments"] for a in golden}
    qa = {q["qa_id"]: q for q in json.loads((DATASET / "all.json").read_text())}
    queries, problems = [], []

    for audio_id, spec in source["files"].items():
        if audio_id not in refs:
            problems.append(f"{audio_id}: not in the golden set")
            continue
        for n, phrase in enumerate(spec["keyword"], 1):
            rx = phrase_regex(phrase)
            evidence = [[a, i] for a in golden for i, s in enumerate(refs[a]) if rx.search(s["text"].lower())]
            if not evidence:
                problems.append(f"{audio_id} keyword {phrase!r}: matches no reference segment")
            if not any(a == audio_id for a, _ in evidence):
                problems.append(f"{audio_id} keyword {phrase!r}: not found in its own file")
            queries.append({"id": f"{audio_id}__k{n}", "kind": "keyword", "text": phrase, "evidence": evidence,
                            "origin": "drafted"})
        for n, item in enumerate(spec["semantic"], 1):
            if "qa" in item:
                q = qa[item["qa"]]
                text, idx, origin = q["question"], q["evidence_segment_indices"], f"all.json:{item['qa']}"
            else:
                text, idx, origin = item["text"], item["evidence"], "drafted"
            idx = list(dict.fromkeys(idx))
            bad = [i for i in idx if not 0 <= i < len(refs[audio_id])]
            if bad:
                problems.append(f"{audio_id} semantic {text!r}: indices out of range {bad}")
            queries.append({"id": f"{audio_id}__s{n}", "kind": "semantic", "text": text,
                            "evidence": [[audio_id, i] for i in idx], "origin": origin})

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    kinds = {k: sum(q["kind"] == k for q in queries) for k in ("keyword", "semantic")}
    out = {"language": "en", "verified": False, "verified_by": None, "counts": kinds,
           "evidence_basis": "dataset/reference_corrected segment indices (see application/evaluation.py)",
           "queries": queries}
    (OUT / "en.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

    lines = ["# English query set: human verification sheet", "",
             "For each query, check that (1) the query is sensible for its kind, keyword = exact term",
             "from the audio and semantic = paraphrase or concept, and (2) **every** listed evidence segment",
             "answers it and **no obviously relevant segment is missing**. Mark problems inline and tell",
             "the agent. When all are OK, set `verified: true` and `verified_by` in `en.json`.", "",
             f"Totals: {kinds['keyword']} keyword, {kinds['semantic']} semantic.", ""]
    for q in queries:
        lines.append(f"## {q['id']} [{q['kind']}] {q['text']}")
        lines.append(f"_origin: {q['origin']}_")
        for a, i in q["evidence"]:
            s = refs[a][i]
            lines.append(f"- `{a}#{i}` {s['speaker']} {s['start']:.1f}s: {s['text']}")
        lines.append("")
    (OUT / "en.review.md").write_text("\n".join(lines))
    multi = sum(len(q["evidence"]) > 1 for q in queries)
    cross = sum(len({a for a, _ in q["evidence"]}) > 1 for q in queries)
    print(f"wrote {len(queries)} queries {kinds}; {multi} with >1 evidence segment; {cross} keyword hits spanning files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
