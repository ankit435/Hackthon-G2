import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, LanguageBadge } from "../components/common";
import { api, uploadFiles } from "../lib/api";
import { formatBytes, formatTime } from "../lib/format";
import type { IngestJob, JobState } from "../lib/types";

type Phase = "ready" | "uploading" | "failed";
interface Item { key: string; file: File; phase: Phase; progress: number; error?: string }

const ACCEPT = ".wav,.mp3,.m4a,.flac,.ogg,.opus,.webm,.aac,.mp4,audio/*";
const STAGES = ["validate", "decode", "transcribe", "diarize", "align", "chunk", "embed", "persist"];
const STATE_LABEL: Record<JobState, string> = {
  queued: "Queued", running: "Processing", ingested: "Indexed", skipped_existing: "Already indexed",
  failed: "Failed", cancelled: "Cancelled",
};
const ACTIVE: JobState[] = ["queued", "running"];

function elapsed(job: IngestJob): string | null {
  if (!job.started_at) return null;
  return formatTime(Math.max(0, (job.finished_at ?? Date.now() / 1000) - job.started_at));
}

function StageSteps({ stage }: { stage: string | null }) {
  const at = stage ? STAGES.indexOf(stage) : -1;
  return (
    <ol className="stages" aria-label="Pipeline stages">
      {STAGES.map((s, i) => (
        <li key={s} className={i < at ? "done" : i === at ? "now" : ""} aria-current={i === at ? "step" : undefined}>{s}</li>
      ))}
    </ol>
  );
}

function JobRow({ job, onCancel }: { job: IngestJob; onCancel: (id: string) => void }) {
  const o = job.outcome;
  return (
    <li className={`upload-item job ${job.state}`}>
      <div className="upload-top">
        {job.state === "queued" && <span className="queue-pos" title="Place in line">#{job.position}</span>}
        <span className="upload-name break">{job.file_name}</span>
        {elapsed(job) && <span className="muted small">{elapsed(job)}</span>}
        <span className={`status ${job.state}`}>
          {job.state === "running" && job.stage ? `${STATE_LABEL.running} · ${job.stage}` : STATE_LABEL[job.state]}
        </span>
        {job.state === "queued" && (
          <button className="icon-btn small" aria-label={`Cancel ${job.file_name}`} onClick={() => onCancel(job.id)}>✕</button>
        )}
      </div>
      {job.state === "running" && <StageSteps stage={job.stage} />}
      {o && (job.state === "ingested" || job.state === "skipped_existing") && (
        <div className="upload-result">
          {o.language && <LanguageBadge code={o.language} />}
          {o.duration_seconds != null && <span>{formatTime(o.duration_seconds)}</span>}
          {job.state === "ingested" && <span>{o.chunk_count} chunks</span>}
          {Object.keys(o.stage_seconds).length > 0 && (
            <span className="muted small">{Object.entries(o.stage_seconds).map(([k, v]) => `${k} ${v.toFixed(1)}s`).join(" · ")}</span>
          )}
          {o.audio_file_id && <Link className="link" to={`/files/${o.audio_file_id}`}>Open transcript →</Link>}
        </div>
      )}
      {job.state === "failed" && (
        <p className="error-text small">{o?.stage ? `${o.stage}: ` : ""}{o?.error ?? "failed"}</p>
      )}
    </li>
  );
}

export function UploadPage({ pollMs = 1500 }: { pollMs?: number }) {
  const [items, setItems] = useState<Item[]>([]);
  const [jobs, setJobs] = useState<IngestJob[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => api.jobs().then((j) => { setJobs(j); setError(null); }).catch(setError), []);
  useEffect(() => { refresh(); }, [refresh]);
  // Poll only while the worker has something to do (or uploads are still adding jobs).
  const active = uploading || jobs.some((j) => ACTIVE.includes(j.state));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [active, pollMs, refresh]);

  // Copy the files now: the input is reset right after, which empties its live FileList before the updater runs.
  const add = (files: FileList | File[]) => { const picked = [...files]; setItems((prev) => [
    ...prev,
    ...picked.map((file) => ({ key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`, file, phase: "ready" as Phase, progress: 0 })),
  ]); };
  const patch = (key: string, p: Partial<Item>) => setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...p } : it)));
  const merge = (incoming: IngestJob[]) => setJobs((prev) => {
    const byId = new Map(prev.map((j) => [j.id, j]));
    incoming.forEach((j) => byId.set(j.id, j));
    return [...byId.values()].sort((a, b) => a.created_at - b.created_at);
  });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };

  // Each file is its own request so it shows its own byte progress. The server only saves and queues it,
  // so a file joins the processing queue the moment its upload finishes, while the next one uploads.
  const start = async () => {
    setUploading(true);
    for (const it of items.filter((i) => i.phase === "ready")) {
      patch(it.key, { phase: "uploading", progress: 0 });
      try {
        merge(await uploadFiles([it.file], (f) => patch(it.key, { progress: f })));
        setItems((prev) => prev.filter((x) => x.key !== it.key));
      } catch (e) {
        patch(it.key, { phase: "failed", error: e instanceof Error ? e.message : String(e) });
      }
    }
    setUploading(false);
  };

  const cancel = (id: string) => api.cancelJob(id).then((j) => merge([j])).catch(setError);

  const ready = items.filter((i) => i.phase === "ready").length;
  const shown = jobs.filter((j) => !hidden.has(j.id));
  const count = (s: JobState) => jobs.filter((j) => j.state === s).length;
  const finished = jobs.filter((j) => !ACTIVE.includes(j.state));

  return (
    <section className="page">
      <header className="page-head">
        <h1>Upload audio</h1>
        <p className="muted">Add one or many recordings. Uploads return right away and go into a queue; a background
          worker transcribes (language auto-detected), splits by speaker, chunks, embeds and indexes them one at a time.
          Each takes roughly the file's own length on a laptop CPU. You can leave this page; the queue keeps going.</p>
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

      {items.length > 0 && (
        <>
          <div className="toolbar">
            <button className="btn primary" onClick={start} disabled={uploading || ready === 0}>
              {uploading ? "Uploading…" : `Upload ${ready} file${ready === 1 ? "" : "s"}`}
            </button>
            <button className="btn ghost" disabled={uploading} onClick={() => setItems([])}>Clear</button>
          </div>
          <ul className="upload-list" aria-label="Files to upload">
            {items.map((it) => (
              <li key={it.key} className={`upload-item ${it.phase}`}>
                <div className="upload-top">
                  <span className="upload-name break">{it.file.name}</span>
                  <span className="muted small">{formatBytes(it.file.size)}</span>
                  <span className={`status ${it.phase}`}>{it.phase === "ready" ? "Ready" : it.phase === "uploading" ? "Uploading" : "Upload failed"}</span>
                  {it.phase === "ready" && !uploading && (
                    <button className="icon-btn small" aria-label={`Remove ${it.file.name}`}
                      onClick={() => setItems((p) => p.filter((x) => x.key !== it.key))}>✕</button>
                  )}
                </div>
                {it.phase === "uploading" && <div className="progress"><span style={{ width: `${Math.round(it.progress * 100)}%` }} /></div>}
                {it.phase === "failed" && <p className="error-text small">{it.error}</p>}
              </li>
            ))}
          </ul>
        </>
      )}

      <ErrorBox error={error} />
      <section className="queue" aria-label="Processing queue">
        <div className="queue-head">
          <h2>Processing queue {active && <span className="live-dot" aria-label="live" />}</h2>
          <div className="queue-stats">
            <span><b>{count("running")}</b> running</span>
            <span><b>{count("queued")}</b> queued</span>
            <span><b>{count("ingested") + count("skipped_existing")}</b> done</span>
            <span><b>{count("failed")}</b> failed</span>
          </div>
          <button className="btn small ghost" disabled={finished.length === 0}
            onClick={() => setHidden(new Set(finished.map((j) => j.id)))}>Clear finished</button>
        </div>
        {shown.length === 0
          ? <p className="muted small">No jobs yet. Uploaded files appear here and are processed one by one.</p>
          : <ul className="upload-list">{shown.map((j) => <JobRow key={j.id} job={j} onCancel={cancel} />)}</ul>}
      </section>
    </section>
  );
}
