"""Retrieval evaluation (PLAN.md §10). High-risk: a bug that inflates a metric never announces itself.

Metric definitions (PROGRESS.md Decisions Log, 2026-09-26):
- Ground truth is a set of EVIDENCE SEGMENTS (audio file + reference segment index), not chunk ids.
  Chunk ids change on every re-ingest; segment indices are stable and map 1:1 across translations.
- A retrieved chunk COVERS an evidence segment when it comes from the same file and their time
  overlap is >= COVER_FRACTION of the shorter of the two.
- recall@k  = |evidence segments covered by the top-k results| / |evidence segments|, per query,
  then the mean over queries. This is the strict IR definition: a query with 3 evidence segments
  scores 1/3 if only one is found.
- hit@k     = 1 if any evidence segment is covered in the top-k, else 0 (reported, not gated).
- MRR       = mean over queries of 1 / (1-based rank of the first covering result), 0 if none.
- speaker accuracy = over every top-k result that overlaps reference speech, whether its predicted
  speaker (mapped per file to reference labels, because diarizer ids are arbitrary) equals the
  reference speaker it overlaps most.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import permutations
from statistics import mean

from domain.models import Hit, LabeledQuery, RefSegment

COVER_FRACTION = 0.5


@dataclass
class QueryScore:
    query_id: str
    kind: str
    recall: dict[int, float]
    hit: dict[int, float]
    reciprocal_rank: float
    covered: dict[int, list[tuple[str, int]]] = field(default_factory=dict)


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def covers(hit: Hit, file: str, seg: RefSegment) -> bool:
    """Same file, and overlap >= COVER_FRACTION of the shorter span.

    Relative to the SHORTER span, so a chunk that fully contains a short segment covers it, and
    so does a short chunk lying fully inside a long segment. A chunk that only grazes a
    neighbouring segment (e.g. a leaked first word) does not. Zero-length spans cover nothing.
    """
    if hit.file != file:
        return False
    shorter = min(hit.end - hit.start, seg.end - seg.start)
    return shorter > 0 and overlap(hit.start, hit.end, seg.start, seg.end) >= COVER_FRACTION * shorter


def score_query(query: LabeledQuery, results: Sequence[Hit], refs: Mapping[str, Sequence[RefSegment]],
                ks: Sequence[int] = (5, 10)) -> QueryScore:
    """Score one query's ranked results. `results` are best-first; only the first max(ks) are used."""
    if not query.evidence:
        raise ValueError(f"query {query.id} has no evidence segments")
    evidence = list(dict.fromkeys(query.evidence))  # duplicates would double-count
    segs = {(f, i): refs[f][i] for f, i in evidence}

    first_rank = None
    covered_at: dict[tuple[str, int], int] = {}  # evidence -> first rank covering it
    for rank, hit in enumerate(results[:max(ks)], start=1):
        hit_covers = [e for e in evidence if covers(hit, e[0], segs[e])]
        if hit_covers and first_rank is None:
            first_rank = rank
        for e in hit_covers:
            covered_at.setdefault(e, rank)

    recall, hit_k, covered = {}, {}, {}
    for k in ks:
        found = [e for e in evidence if covered_at.get(e, k + 1) <= k]
        recall[k] = len(found) / len(evidence)
        hit_k[k] = 1.0 if found else 0.0
        covered[k] = found
    return QueryScore(query.id, query.kind, recall, hit_k, 1.0 / first_rank if first_rank else 0.0, covered)


def speaker_mapping(chunks_by_file: Mapping[str, Sequence[Hit]], refs: Mapping[str, Sequence[RefSegment]]) -> dict[str, dict[str, str]]:
    """Per file, the predicted→reference label permutation with the greatest total overlap time.

    Tries every one-to-one assignment (2 speakers → 2 permutations). Being one-to-one means two
    predicted labels can never both be mapped to the same reference speaker, which would inflate
    accuracy. Predicted labels beyond the number of reference labels stay unmapped (always wrong).
    """
    mapping = {}
    for file, chunks in chunks_by_file.items():
        ref_labels = sorted({s.speaker for s in refs[file]})
        pred_labels = sorted({c.speaker for c in chunks})
        time = defaultdict(float)
        for c in chunks:
            for s in refs[file]:
                time[(c.speaker, s.speaker)] += overlap(c.start, c.end, s.start, s.end)
        best, best_total = {}, -1.0
        for perm in permutations(ref_labels, min(len(pred_labels), len(ref_labels))):
            candidate = dict(zip(pred_labels, perm))
            total = sum(time[(p, r)] for p, r in candidate.items())
            if total > best_total:
                best, best_total = candidate, total
        mapping[file] = best
    return mapping


def speaker_correct(hit: Hit, refs: Mapping[str, Sequence[RefSegment]], mapping: Mapping[str, Mapping[str, str]]) -> bool | None:
    """True/False against the reference speaker the hit overlaps most; None if it overlaps no reference speech."""
    per_speaker = defaultdict(float)
    for s in refs[hit.file]:
        per_speaker[s.speaker] += overlap(hit.start, hit.end, s.start, s.end)
    if not per_speaker or max(per_speaker.values()) == 0:
        return None
    truth = max(sorted(per_speaker), key=per_speaker.get)
    return mapping.get(hit.file, {}).get(hit.speaker) == truth


def summarize(scores: Sequence[QueryScore], ks: Sequence[int] = (5, 10)) -> dict:
    """Means overall and per query kind. Empty groups are omitted, never reported as 0 or 1."""
    def agg(group: Sequence[QueryScore]) -> dict:
        return {"queries": len(group), "mrr": round(mean(s.reciprocal_rank for s in group), 4),
                **{f"recall@{k}": round(mean(s.recall[k] for s in group), 4) for k in ks},
                **{f"hit@{k}": round(mean(s.hit[k] for s in group), 4) for k in ks}}
    out = {"overall": agg(scores)} if scores else {}
    for kind in sorted({s.kind for s in scores}):
        out[kind] = agg([s for s in scores if s.kind == kind])
    return out


SearchFn = Callable[[str, int], "Sequence[Hit]"]


def _percentile(sorted_values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (no interpolation): the smallest value with >= p% of samples at or below it."""
    import math
    return sorted_values[max(0, math.ceil(p / 100 * len(sorted_values)) - 1)]


class EvaluationService:
    """Runs a labeled query set through the SAME SearchService methods the API serves (PLAN.md §7A, §10).

    Primary metrics come from `search` (fused). Per-branch recall comes from the diagnostic
    `keyword` / `semantic` methods. It reports and never writes; pytest owns pass/fail.
    """

    def __init__(self, search, files, chunks) -> None:
        self._search, self._files, self._chunks = search, files, chunks

    async def _chunks_by_file(self, checksums: Mapping[str, str]) -> dict[str, list[Hit]]:
        out = {}
        for audio_id, checksum in checksums.items():
            f = await self._files.find_by_checksum(checksum)
            if f is None:
                raise ValueError(f"{audio_id} is not ingested (checksum {checksum[:12]}…)")
            out[audio_id] = [Hit(audio_id, c.start_time, c.end_time, c.speaker) for c in await self._chunks.list_by_file(f.id)]
        return out

    async def run(self, queries: Sequence[LabeledQuery], refs: Mapping[str, Sequence[RefSegment]],
                  checksums: Mapping[str, str], file_names: Mapping[str, str], top_k: int = 10,
                  ks: Sequence[int] = (5, 10)) -> dict:
        """`checksums`: audio_id -> sha256 of ingested audio; `file_names`: stored file_name -> audio_id."""
        import time

        if top_k < max(ks):
            raise ValueError(f"top_k {top_k} < max k {max(ks)} would make recall@{max(ks)} meaningless")
        mapping = speaker_mapping(await self._chunks_by_file(checksums), refs)

        def to_hits(items) -> list[Hit]:
            # a result from a file outside the evaluated set can never be relevant; keep its rank slot
            return [Hit(file_names.get(r.file_name, f"<other:{r.file_name}>"), r.start_time, r.end_time, r.speaker) for r in items]

        await self._search.search(queries[0].text, top_k)  # warm-up; excluded from latency (§2: warmed-up)
        fused, keyword, semantic, latency_ms, speaker = [], [], [], [], []
        for q in queries:
            t0 = time.perf_counter()
            results = to_hits(await self._search.search(q.text, top_k))
            latency_ms.append((time.perf_counter() - t0) * 1000)
            fused.append(score_query(q, results, refs, ks))
            speaker += [speaker_correct(h, refs, mapping) for h in results if h.file in refs]
            keyword.append(score_query(q, to_hits(await self._search.keyword(q.text, top_k)), refs, ks))
            semantic.append(score_query(q, to_hits(await self._search.semantic(q.text, top_k)), refs, ks))

        judged = [s for s in speaker if s is not None]
        latency_ms.sort()
        return {
            "config": {**self._search.config, "top_k": top_k, "queries": len(queries)},
            "fused": summarize(fused, ks),
            "keyword_branch_only": summarize(keyword, ks),
            "semantic_branch_only": summarize(semantic, ks),
            "speaker_accuracy": {"accuracy": round(sum(judged) / len(judged), 4) if judged else None,
                                 "judged_results": len(judged), "unjudged_results": len(speaker) - len(judged),
                                 "mapping": mapping},
            "latency_ms": {"p50": round(_percentile(latency_ms, 50), 2), "p95": round(_percentile(latency_ms, 95), 2),
                           "p99": round(_percentile(latency_ms, 99), 2), "max": round(latency_ms[-1], 2)},
            "per_query": [{"id": s.query_id, "kind": s.kind, **{f"recall@{k}": s.recall[k] for k in ks},
                           "rr": round(s.reciprocal_rank, 4),
                           "keyword_recall@10": kw.recall[max(ks)], "semantic_recall@10": se.recall[max(ks)]}
                          for s, kw, se in zip(fused, keyword, semantic)],
        }
