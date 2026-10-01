import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Empty, ErrorBox, LanguageBadge, PlayIcon, Spinner } from "../components/common";
import { api } from "../lib/api";
import { formatTime, languageName } from "../lib/format";
import { usePlayer } from "../lib/player";
import type { FileSummary } from "../lib/types";

type SortKey = "file_name" | "duration_seconds" | "chunk_count" | "created_at";

export function LibraryPage() {
  const [files, setFiles] = useState<FileSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("");
  const [lang, setLang] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("file_name");
  const navigate = useNavigate();
  const player = usePlayer();

  useEffect(() => { api.files().then(setFiles).catch(setError); }, []);

  const languages = useMemo(() => [...new Set((files ?? []).map((f) => f.language))].sort(), [files]);
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (files ?? [])
      .filter((f) => (lang === "all" || f.language === lang) && (!needle || f.file_name.toLowerCase().includes(needle)))
      .sort((a, b) => {
        const x = a[sort] ?? "", y = b[sort] ?? "";
        return typeof x === "number" && typeof y === "number" ? y - x : String(x).localeCompare(String(y));
      });
  }, [files, filter, lang, sort]);
  const totalSeconds = (files ?? []).reduce((s, f) => s + f.duration_seconds, 0);
  const totalChunks = (files ?? []).reduce((s, f) => s + (f.chunk_count ?? 0), 0);

  return (
    <section className="page">
      <header className="page-head row">
        <div>
          <h1>Library</h1>
          <p className="muted">Every indexed recording. Open one to read and play its full transcript.</p>
        </div>
        <Link to="/upload" className="btn primary">Upload audio</Link>
      </header>

      {files && (
        <div className="stats">
          <div className="stat"><b>{files.length}</b><span>files</span></div>
          <div className="stat"><b>{formatTime(totalSeconds)}</b><span>of audio</span></div>
          <div className="stat"><b>{totalChunks}</b><span>chunks</span></div>
          <div className="stat"><b>{languages.length}</b><span>languages</span></div>
        </div>
      )}

      <div className="toolbar">
        <input className="text-input" placeholder="Filter by name" value={filter} onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter files by name" />
        <div className="chips">
          <button className={`chip ${lang === "all" ? "on" : ""}`} onClick={() => setLang("all")}>All</button>
          {languages.map((l) => (
            <button key={l} className={`chip ${lang === l ? "on" : ""}`} onClick={() => setLang(l)}>{languageName(l)}</button>
          ))}
        </div>
        <label className="inline">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="file_name">Name</option>
            <option value="duration_seconds">Duration</option>
            <option value="chunk_count">Chunks</option>
            <option value="created_at">Date added</option>
          </select>
        </label>
      </div>

      <ErrorBox error={error} />
      {!files && !error && <Spinner label="Loading files" />}
      {files && files.length === 0 && <Empty>Nothing indexed yet. <Link to="/upload">Upload some audio</Link> to get started.</Empty>}
      {files && files.length > 0 && (
        <table className="table">
          <thead>
            <tr><th /><th>File</th><th>Language</th><th>Duration</th><th>Chunks</th><th>Speakers</th><th>Added</th></tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f.id} className="clickable" onClick={() => navigate(`/files/${f.id}`)}>
                <td>
                  <button className="icon-btn small" aria-label={`Play ${f.file_name}`}
                    onClick={(e) => { e.stopPropagation(); player.play({ fileId: f.id, fileName: f.file_name }, 0); }}>
                    <PlayIcon />
                  </button>
                </td>
                <td><Link to={`/files/${f.id}`} onClick={(e) => e.stopPropagation()}>{f.file_name}</Link></td>
                <td><LanguageBadge code={f.language} />
                  <span className="muted small"> {Math.round(f.language_probability * 100)}%</span></td>
                <td>{formatTime(f.duration_seconds)}</td>
                <td>{f.chunk_count ?? "–"}</td>
                <td>{f.speakers?.length ?? "–"}</td>
                <td className="muted">{f.created_at ? new Date(f.created_at).toLocaleDateString() : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
