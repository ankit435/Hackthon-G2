import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, LanguageBadge } from "../components/common";
import { uploadFiles } from "../lib/api";
import { formatBytes, formatTime } from "../lib/format";
import type { IngestOutcome } from "../lib/types";

type Phase = "queued" | "uploading" | "processing" | "ingested" | "skipped_existing" | "failed";
interface Item { key: string; file: File; phase: Phase; progress: number; outcome?: IngestOutcome; error?: string }

const ACCEPT = ".wav,.mp3,.m4a,.flac,.ogg,.opus,.webm,.aac,.mp4,audio/*";
const PHASE_LABEL: Record<Phase, string> = {
  queued: "Queued", uploading: "Uploading", processing: "Transcribing & indexing…", ingested: "Indexed",
  skipped_existing: "Already indexed", failed: "Failed",
};

export function UploadPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [running, setRunning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);

  const add = (files: FileList | File[]) => setItems((prev) => [
    ...prev,
    ...[...files].map((file) => ({ key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`, file, phase: "queued" as Phase, progress: 0 })),
  ]);
  const patch = (key: string, p: Partial<Item>) => setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...p } : it)));

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };

  // One request per file, in order: each file shows its own upload progress and its own outcome as soon as
  // it finishes, and one bad file never holds back the others.
  const start = async () => {
    setRunning(true);
    setError(null);
    for (const it of items.filter((i) => i.phase === "queued")) {
      patch(it.key, { phase: "uploading", progress: 0 });
      try {
        const [outcome] = await uploadFiles([it.file], (f) => patch(it.key, f >= 1 ? { phase: "processing", progress: 1 } : { progress: f }));
        patch(it.key, { phase: outcome.status, outcome, error: outcome.error ?? undefined });
      } catch (e) {
        patch(it.key, { phase: "failed", error: e instanceof Error ? e.message : String(e) });
      }
    }
    setRunning(false);
  };

  const queued = items.filter((i) => i.phase === "queued").length;
  const done = items.filter((i) => ["ingested", "skipped_existing", "failed"].includes(i.phase)).length;

  return (
    <section className="page">
      <header className="page-head">
        <h1>Upload audio</h1>
        <p className="muted">Add one or many recordings. Each is transcribed (language auto-detected), split by speaker,
          chunked, embedded and indexed. That takes roughly the file's own length on a laptop CPU, so large batches take a while.</p>
      </header>

      <div className={`dropzone ${dragging ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)} onDrop={onDrop} onClick={() => input.current?.click()}
        role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 7 8h3v6h4V8h3zM5 16v3h14v-3h2v5H3v-5z" /></svg>
        <p><b>Drop audio files here</b> or click to choose</p>
        <p className="muted small">WAV, MP3, M4A, FLAC, OGG, OPUS, WEBM, AAC · multiple files allowed</p>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden
          onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
      </div>

      <ErrorBox error={error} />
      {items.length > 0 && (
        <>
          <div className="toolbar">
            <button className="btn primary" onClick={start} disabled={running || queued === 0}>
              {running ? "Working…" : `Upload & index ${queued} file${queued === 1 ? "" : "s"}`}
            </button>
            <button className="btn ghost" disabled={running} onClick={() => setItems((p) => p.filter((i) => i.phase === "queued"))}>Clear finished</button>
            <button className="btn ghost" disabled={running} onClick={() => setItems([])}>Clear all</button>
            <span className="muted">{done}/{items.length} done</span>
          </div>
          <ul className="upload-list">
            {items.map((it) => (
              <li key={it.key} className={`upload-item ${it.phase}`}>
                <div className="upload-top">
                  <span className="upload-name break">{it.file.name}</span>
                  <span className="muted small">{formatBytes(it.file.size)}</span>
                  <span className={`status ${it.phase}`}>{PHASE_LABEL[it.phase]}</span>
                  {it.phase === "queued" && !running && (
                    <button className="icon-btn small" aria-label={`Remove ${it.file.name}`}
                      onClick={() => setItems((p) => p.filter((x) => x.key !== it.key))}>✕</button>
                  )}
                </div>
                {(it.phase === "uploading" || it.phase === "processing") && (
                  <div className={`progress ${it.phase === "processing" ? "indeterminate" : ""}`}>
                    <span style={{ width: `${Math.round(it.progress * 100)}%` }} />
                  </div>
                )}
                {it.outcome && it.phase !== "failed" && (
                  <div className="upload-result">
                    {it.outcome.language && <LanguageBadge code={it.outcome.language} />}
                    {it.outcome.duration_seconds != null && <span>{formatTime(it.outcome.duration_seconds)}</span>}
                    {it.phase === "ingested" && <span>{it.outcome.chunk_count} chunks</span>}
                    {Object.keys(it.outcome.stage_seconds).length > 0 && (
                      <span className="muted small">{Object.entries(it.outcome.stage_seconds).map(([k, v]) => `${k} ${v.toFixed(1)}s`).join(" · ")}</span>
                    )}
                    {it.outcome.audio_file_id && <Link className="link" to={`/files/${it.outcome.audio_file_id}`}>Open transcript →</Link>}
                  </div>
                )}
                {it.phase === "failed" && (
                  <p className="error-text small">{it.outcome?.stage ? `${it.outcome.stage}: ` : ""}{it.error ?? "failed"}</p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
