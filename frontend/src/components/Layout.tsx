import { Link, NavLink, Outlet } from "react-router-dom";
import { formatTime } from "../lib/format";
import { usePlayer } from "../lib/player";
import { Bubbles } from "./Bubbles";
import { PlayIcon } from "./common";
import { EqBars } from "./visuals";

const NAV = [
  { to: "/search", label: "Search", icon: "M11 4a7 7 0 1 0 4.4 12.4l4.1 4.1 1.4-1.4-4.1-4.1A7 7 0 0 0 11 4zm0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10z" },
  { to: "/library", label: "Library", icon: "M4 5h4v14H4zm6 0h4v14h-4zm6.5.6 3.9 1 -3.5 13.5-3.9-1z" },
  { to: "/upload", label: "Upload", icon: "M12 3 7 8h3v6h4V8h3zM5 16v3h14v-3h2v5H3v-5z" },
  { to: "/ask", label: "Ask", icon: "M4 4h16v12H8l-4 4zm4 5v2h8V9zm0-3v2h8V6z" },
  { to: "/evaluation", label: "Evaluation", icon: "M4 20V10h3v10zm6 0V4h3v16zm6 0v-7h3v7z" },
  { to: "/system", label: "System", icon: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm8.9 5-.1-2 2-1.6-2-3.4-2.4.8-1.6-1L16.4 3h-4l-.5 2.4-1.7 1-2.3-.9-2 3.5 1.9 1.6v2l-2 1.6 2 3.4 2.4-.8 1.6 1 .4 2.5h4l.5-2.5 1.7-1 2.3.9 2-3.5z" },
];

function PlayerBar() {
  const p = usePlayer();
  if (!p.track) return null;
  const pct = p.duration ? Math.min(100, (p.time / p.duration) * 100) : 0;
  return (
    <div className="player-bar" aria-label="Audio player">
      <button className="icon-btn primary" onClick={p.toggle} aria-label={p.playing ? "Pause" : "Play"}>
        <PlayIcon playing={p.playing} />
      </button>
      <div className="player-meta">
        <Link to={`/files/${p.track.fileId}`} className="player-title"><EqBars playing={p.playing} /> {p.track.fileName}</Link>
        <div className="player-time">
          {formatTime(p.time)} / {formatTime(p.duration)}
          {p.segmentEnd !== null && <span className="muted"> · segment ends {formatTime(p.segmentEnd)}</span>}
          {p.error && <span className="error-text"> · {p.error}</span>}
        </div>
      </div>
      <input
        className="scrubber" type="range" min={0} max={p.duration || 0} step={0.1} value={p.time}
        onChange={(e) => p.seek(Number(e.target.value))} aria-label="Seek"
        style={{ ["--pct" as string]: `${pct}%` }}
      />
      <button className="icon-btn" onClick={p.stop} aria-label="Close player">✕</button>
    </div>
  );
}

export function Layout() {
  const { track } = usePlayer();
  return (
    <div className={`app ${track ? "with-player" : ""}`}>
      <Bubbles />
      <aside className="sidebar">
        <Link to="/search" className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M3 12h2m2-5v10m4-13v16m4-11v6m4-9v12m2-6h1" /></svg>
          </span>
          <span>Audio Search</span>
        </Link>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d={n.icon} /></svg>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <a className="nav-link subtle" href="/docs" target="_blank" rel="noreferrer">API docs ↗</a>
      </aside>
      <main className="content">
        <Outlet />
      </main>
      <PlayerBar />
    </div>
  );
}
