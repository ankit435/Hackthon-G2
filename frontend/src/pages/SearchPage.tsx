import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { HitCard } from "../components/HitCard";
import { Empty, ErrorBox, highlightTerms, Spinner } from "../components/common";
import { api } from "../lib/api";
import type { SearchHit, SearchMode } from "../lib/types";

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "Keyword + semantic, fused with weighted RRF (the graded path)" },
  { value: "keyword", label: "Keyword", hint: "Diagnostic: full-text branch only (exact words, stemmed)" },
  { value: "semantic", label: "Semantic", hint: "Diagnostic: embedding branch only (meaning, cross-lingual)" },
];
const EXAMPLES = ["token bucket burst capacity", "why use a temporary redirect", "idempotency key", "限流器", "cómo evitar cobros dobles"];

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const mode = (params.get("mode") as SearchMode) || "hybrid";
  const topK = Number(params.get("k") ?? 10);
  const [draft, setDraft] = useState(q);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => setDraft(q), [q]);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    let live = true;
    const t0 = performance.now();
    setLoading(true);
    setError(null);
    api.search(q, mode, topK)
      .then((h) => { if (live) { setHits(h); setElapsed(performance.now() - t0); } })
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [q, mode, topK]);

  const update = (next: Record<string, string>) => setParams({ q, mode, k: String(topK), ...next });
  const submit = (e: FormEvent) => { e.preventDefault(); update({ q: draft.trim() }); };

  return (
    <section className="page">
      <header className="page-head">
        <h1>Search conversations</h1>
        <p className="muted">Find exact words or similar meaning across every indexed recording, in any language.
          Each hit gives the file, the timestamp and the speaker.</p>
      </header>

      <form className="search-form" onSubmit={submit} role="search">
        <input
          className="search-input" value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus
          placeholder="e.g. how do they avoid charging a customer twice?" aria-label="Search query" maxLength={1000}
        />
        <button className="btn primary" type="submit" disabled={!draft.trim()}>Search</button>
      </form>

      <div className="toolbar">
        <div className="segmented" role="radiogroup" aria-label="Search mode">
          {MODES.map((m) => (
            <button key={m.value} type="button" role="radio" aria-checked={mode === m.value} title={m.hint}
              className={mode === m.value ? "on" : ""} onClick={() => update({ mode: m.value })}>{m.label}</button>
          ))}
        </div>
        <label className="inline">
          Results
          <select value={topK} onChange={(e) => update({ k: e.target.value })}>
            {[5, 10, 20, 50].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        {hits && !loading && (
          <span className="muted">{hits.length} result{hits.length === 1 ? "" : "s"}
            {elapsed !== null && ` · ${Math.round(elapsed)} ms`}</span>
        )}
      </div>
      {mode !== "hybrid" && <p className="note">Diagnostic mode: {MODES.find((m) => m.value === mode)?.hint}.</p>}

      <ErrorBox error={error} />
      {loading && <Spinner label="Searching" />}
      {!q && (
        <Empty>
          <p>Try one of these:</p>
          <div className="chips">
            {EXAMPLES.map((ex) => <button key={ex} className="chip" onClick={() => update({ q: ex })}>{ex}</button>)}
          </div>
        </Empty>
      )}
      {hits && !loading && hits.length === 0 && <Empty>No results for “{q}”.</Empty>}
      <div className="hits">
        {hits?.map((h, i) => <HitCard key={h.chunk_id} hit={h} rank={i + 1} terms={highlightTerms(q)} />)}
      </div>
    </section>
  );
}
