import { useState } from "react";
import { ErrorBox, Spinner } from "../components/common";
import { api } from "../lib/api";
import type { EvaluationReport, MetricGroup } from "../lib/types";

// Fixed primary targets (PLAN.md §2): recall@5 >= 0.80, recall@10 >= 0.90, speaker >= 0.90, p95 < 500 ms.
const TARGETS: Record<string, number> = { "recall@5": 0.8, "recall@10": 0.9 };
const COLUMNS = ["recall@5", "recall@10", "hit@5", "hit@10", "mrr"];

function Cell({ name, value }: { name: string; value: number | undefined }) {
  if (value === undefined) return <td>–</td>;
  const target = TARGETS[name];
  const cls = target === undefined ? "" : value >= target ? "pass" : "fail";
  return <td className={cls} title={target !== undefined ? `target ≥ ${target}` : undefined}>{value.toFixed(3)}</td>;
}

function MetricTable({ title, groups }: { title: string; groups?: Record<string, MetricGroup> }) {
  if (!groups) return null;
  return (
    <div className="card">
      <h2>{title}</h2>
      <table className="table compact">
        <thead><tr><th>Queries</th><th>n</th>{COLUMNS.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {Object.entries(groups).map(([kind, g]) => (
            <tr key={kind}><td>{kind}</td><td>{g.queries}</td>{COLUMNS.map((c) => <Cell key={c} name={c} value={g[c]} />)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EvaluationPage() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try { setReport(await api.evaluation()); } catch (e) { setError(e); } finally { setLoading(false); }
  };

  const s = report?.summary;
  const speaker = s?.speaker_accuracy?.accuracy ?? null;
  const p95 = s?.latency_ms?.p95;

  return (
    <section className="page">
      <header className="page-head row">
        <div>
          <h1>Evaluation</h1>
          <p className="muted">Runs the labelled English query set through the graded search path and reports recall, MRR,
            speaker accuracy and latency against the fixed targets. Takes a minute or two.</p>
        </div>
        <button className="btn primary" onClick={run} disabled={loading}>{loading ? "Running…" : "Run evaluation"}</button>
      </header>
      <ErrorBox error={error} />
      {loading && <Spinner label="Evaluating (every query runs through /search)" />}
      {s && (
        <>
          <div className="stats">
            <div className={`stat ${(s.fused?.overall?.["recall@5"] ?? 0) >= 0.8 ? "pass" : "fail"}`}>
              <b>{s.fused?.overall?.["recall@5"]?.toFixed(3) ?? "–"}</b><span>recall@5 (≥ 0.80)</span></div>
            <div className={`stat ${(s.fused?.overall?.["recall@10"] ?? 0) >= 0.9 ? "pass" : "fail"}`}>
              <b>{s.fused?.overall?.["recall@10"]?.toFixed(3) ?? "–"}</b><span>recall@10 (≥ 0.90)</span></div>
            <div className={`stat ${speaker !== null && speaker >= 0.9 ? "pass" : "fail"}`}>
              <b>{speaker?.toFixed(3) ?? "–"}</b><span>speaker accuracy (≥ 0.90)</span></div>
            <div className={`stat ${p95 !== undefined && p95 < 500 ? "pass" : "fail"}`}>
              <b>{p95 !== undefined ? `${Math.round(p95)} ms` : "–"}</b><span>latency p95 (&lt; 500 ms)</span></div>
          </div>
          <MetricTable title="Hybrid search (graded)" groups={s.fused} />
          <MetricTable title="Keyword branch only (diagnostic)" groups={s.keyword_branch_only} />
          <MetricTable title="Semantic branch only (diagnostic)" groups={s.semantic_branch_only} />
          <div className="card">
            <h2>Configuration</h2>
            <pre className="code">{JSON.stringify(report?.config, null, 2)}</pre>
          </div>
        </>
      )}
    </section>
  );
}
