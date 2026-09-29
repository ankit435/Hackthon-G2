import { useEffect, useState } from "react";
import { ErrorBox, Spinner } from "../components/common";
import { api } from "../lib/api";

const LABELS: Record<string, string> = {
  embedding_model: "Embedding model", whisper_model: "Transcription (Whisper)", diarization_model: "Diarization",
  reranker: "Cross-encoder re-ranker", rerank_depth: "Re-rank depth", rrf_k: "RRF k", weights: "Fusion weights",
  candidate_depth_multiplier: "Per-branch depth (× top-K)", answer_enabled: "LLM answers (/answer)",
};

function show(value: unknown): string {
  if (value === null || value === undefined) return "off";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k} ${v}`).join(" · ");
  return String(value);
}

export function SystemPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { api.config().then(setConfig).catch(setError); }, []);

  return (
    <section className="page">
      <header className="page-head">
        <h1>System</h1>
        <p className="muted">The models and search settings the running API is using. Settings come from the server's
          environment (<code>.env</code>); change them there and restart.</p>
      </header>
      <ErrorBox error={error} />
      {!config && !error && <Spinner label="Loading configuration" />}
      {config && (
        <div className="card">
          <dl className="kv">
            {Object.entries(config).map(([k, v]) => (
              <div key={k}><dt>{LABELS[k] ?? k}</dt><dd>{show(v)}</dd></div>
            ))}
          </dl>
        </div>
      )}
      <div className="card">
        <h2>API</h2>
        <p>Interactive API documentation: <a className="link" href="/docs" target="_blank" rel="noreferrer">Swagger UI</a> ·{" "}
          <a className="link" href="/redoc" target="_blank" rel="noreferrer">ReDoc</a></p>
      </div>
    </section>
  );
}
