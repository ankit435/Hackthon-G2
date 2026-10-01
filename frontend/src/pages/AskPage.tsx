import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, LanguageBadge, PlayIcon, SpeakerBadge, Spinner } from "../components/common";
import { api, ApiError } from "../lib/api";
import { formatRange } from "../lib/format";
import { usePlayer } from "../lib/player";
import type { AnswerResponse } from "../lib/types";

/** Turns "[1]" markers in the answer into buttons that play the cited segment. */
function withCitations(text: string, onCite: (n: number) => void): ReactNode[] {
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const m = /^\[(\d+)\]$/.exec(part);
    return m ? <button key={i} className="cite" onClick={() => onCite(Number(m[1]))}>{part}</button> : part;
  });
}

export function AskPage() {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const player = usePlayer();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.answer(question.trim(), topK));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 503
        ? new Error("Answer generation is not configured on the server (set NVIDIA_API_KEY). Search still works.")
        : err);
    } finally {
      setLoading(false);
    }
  };

  const playCitation = (n: number) => {
    const c = result?.citations.find((x) => x.number === n);
    if (c) player.play({ fileId: c.audio_file_id, fileName: c.file_name }, c.start_time, c.end_time);
  };

  return (
    <section className="page">
      <header className="page-head">
        <h1>Ask a question</h1>
        <p className="muted">Hybrid search finds the evidence first; an LLM then answers only from those segments and cites
          them. Click a citation to hear it.</p>
      </header>
      <form className="ask-form" onSubmit={submit}>
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} maxLength={1000}
          placeholder="e.g. How does the payment service avoid charging a customer twice?" aria-label="Question" />
        <div className="toolbar">
          <button className="btn primary" type="submit" disabled={loading || !question.trim()}>Ask</button>
          <label className="inline">Evidence segments
            <select value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
              {[3, 5, 8, 10].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
      </form>
      <ErrorBox error={error} />
      {loading && <Spinner label="Retrieving evidence and generating an answer" />}
      {result && (
        <div className="answer">
          <div className="answer-text">{withCitations(result.answer, playCitation)}</div>
          <h2>Sources</h2>
          <ol className="citations">
            {result.citations.map((c) => (
              <li key={c.number}>
                <button className="icon-btn small" onClick={() => playCitation(c.number)} aria-label={`Play source ${c.number}`}><PlayIcon /></button>
                <div>
                  <div className="hit-head">
                    <b>[{c.number}]</b>
                    <Link to={`/files/${c.audio_file_id}?chunk=${c.chunk_id}`} className="hit-file">{c.file_name}</Link>
                    <span className="time">{formatRange(c.start_time, c.end_time)}</span>
                    <SpeakerBadge speaker={c.speaker} />
                    <LanguageBadge code={c.language} />
                  </div>
                  <p>{c.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
