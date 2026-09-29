import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ErrorBox, Highlight, LanguageBadge, PlayIcon, SpeakerBadge, Spinner, highlightTerms } from "../components/common";
import { api } from "../lib/api";
import { activeChunkIndex, formatRange, formatTime } from "../lib/format";
import { usePlayer } from "../lib/player";
import type { Transcript } from "../lib/types";

export function FilePage() {
  const { fileId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Transcript | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [find, setFind] = useState("");
  const [matchCursor, setMatchCursor] = useState(0);
  const [hiddenSpeakers, setHiddenSpeakers] = useState<Set<string>>(new Set());
  const [follow, setFollow] = useState(true);
  const [copied, setCopied] = useState<string | null>(null);
  const rows = useRef<Map<string, HTMLLIElement>>(new Map());
  const player = usePlayer();

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api.transcript(fileId).then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [fileId]);

  const chunks = data?.chunks ?? [];
  const track = data ? { fileId: data.file.id, fileName: data.file.file_name } : null;
  const onThisFile = player.track?.fileId === fileId;
  const playingIndex = onThisFile ? activeChunkIndex(chunks, player.time) : -1;
  const selectedId = params.get("chunk");
  const selectedIndex = selectedId ? chunks.findIndex((c) => c.id === selectedId) : -1;
  // While audio plays, the playhead decides the current chunk; when paused, the user's selection
  // (j/k, prev/next, find, deep link) wins, so navigating while paused visibly moves.
  const currentIndex = onThisFile && player.playing && playingIndex >= 0
    ? playingIndex : selectedIndex >= 0 ? selectedIndex : playingIndex;

  const terms = useMemo(() => highlightTerms(find), [find]);
  const matches = useMemo(() => {
    if (!terms.length) return [];
    const re = new RegExp(terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "iu");
    return chunks.map((c, i) => (re.test(c.text) ? i : -1)).filter((i) => i >= 0);
  }, [chunks, terms]);

  const scrollTo = useCallback((id: string) => {
    rows.current.get(id)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  // Typing in "Find" jumps to the first match right away (Enter / arrows step through the rest).
  // Keyed on the search text only, so new playback positions never yank the view back to a match.
  useEffect(() => {
    if (matches.length && chunks[matches[0]]) scrollTo(chunks[matches[0]].id);
  }, [find]);
  // Deep link (?chunk=) from a search hit or citation: scroll to it once the transcript is loaded.
  useEffect(() => { if (data && selectedId) scrollTo(selectedId); }, [data, selectedId, scrollTo]);
  // Follow the playhead.
  useEffect(() => {
    if (follow && playingIndex >= 0 && chunks[playingIndex]) scrollTo(chunks[playingIndex].id);
  }, [follow, playingIndex, chunks, scrollTo]);

  const playAt = useCallback((i: number) => {
    const c = chunks[i];
    if (!c || !track) return;
    setParams({ chunk: c.id }, { replace: true });
    player.play(track, c.start_time);
  }, [chunks, track, player, setParams]);

  const step = useCallback((delta: number) => {
    const from = currentIndex >= 0 ? currentIndex : delta > 0 ? -1 : chunks.length;
    const next = Math.min(chunks.length - 1, Math.max(0, from + delta));
    if (onThisFile && player.playing) playAt(next);
    else if (chunks[next]) { setParams({ chunk: chunks[next].id }, { replace: true }); scrollTo(chunks[next].id); }
  }, [currentIndex, chunks, onThisFile, player.playing, playAt, setParams, scrollTo]);

  // Keyboard: j / k = next / previous chunk, space = play/pause (ignored while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, button")) return;
      if (e.key === "j") step(1);
      else if (e.key === "k") step(-1);
      else if (e.key === " ") {
        e.preventDefault();
        if (onThisFile) player.toggle(); else playAt(Math.max(0, currentIndex));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onThisFile, player, playAt, currentIndex]);

  const jumpToMatch = (dir: number) => {
    if (!matches.length) return;
    const next = (matchCursor + dir + matches.length) % matches.length;
    setMatchCursor(next);
    const c = chunks[matches[next]];
    setParams({ chunk: c.id }, { replace: true });
    scrollTo(c.id);
  };

  const copyLink = (id: string) => {
    const url = `${window.location.origin}${window.location.pathname}?chunk=${id}`;
    navigator.clipboard?.writeText(url).then(() => { setCopied(id); setTimeout(() => setCopied(null), 1500); });
  };

  if (error) return <section className="page"><Link to="/library" className="link">← Library</Link><ErrorBox error={error} /></section>;
  if (!data || !track) return <section className="page"><Spinner label="Loading transcript" /></section>;
  const speakers = data.file.speakers ?? [];

  return (
    <section className="page transcript-page">
      <Link to="/library" className="link">← Library</Link>
      <header className="page-head">
        <h1 className="break">{data.file.file_name}</h1>
        <div className="meta-row">
          <LanguageBadge code={data.file.language} />
          <span>{formatTime(data.file.duration_seconds)}</span>
          <span>{chunks.length} chunks</span>
          {speakers.map((s) => <SpeakerBadge key={s} speaker={s} />)}
        </div>
      </header>

      <div className="transcript-controls">
        <button className="btn primary" onClick={() => (onThisFile ? player.toggle() : playAt(Math.max(0, currentIndex)))}>
          <PlayIcon playing={onThisFile && player.playing} /> {onThisFile && player.playing ? "Pause" : "Play"}
        </button>
        <button className="btn" onClick={() => step(-1)} disabled={currentIndex <= 0} title="Previous chunk (k)">‹ Prev</button>
        <button className="btn" onClick={() => step(1)} disabled={currentIndex >= chunks.length - 1} title="Next chunk (j)">Next ›</button>
        <span className="muted">{currentIndex >= 0 ? `Chunk ${currentIndex + 1} / ${chunks.length}` : `${chunks.length} chunks`}</span>
        <label className="inline"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow playback</label>
        <div className="find">
          <input className="text-input" placeholder="Find in transcript" value={find}
            onChange={(e) => { setFind(e.target.value); setMatchCursor(0); }}
            onKeyDown={(e) => e.key === "Enter" && jumpToMatch(e.shiftKey ? -1 : 1)} aria-label="Find in transcript" />
          {terms.length > 0 && (
            <>
              <span className="muted small">{matches.length ? `${matchCursor + 1}/${matches.length}` : "0 matches"}</span>
              <button className="icon-btn small" onClick={() => jumpToMatch(-1)} aria-label="Previous match">↑</button>
              <button className="icon-btn small" onClick={() => jumpToMatch(1)} aria-label="Next match">↓</button>
            </>
          )}
        </div>
        {speakers.length > 1 && (
          <div className="chips" aria-label="Show speakers">
            {speakers.map((s) => (
              <button key={s} className={`chip ${hiddenSpeakers.has(s) ? "" : "on"}`} onClick={() => setHiddenSpeakers((prev) => {
                const next = new Set(prev);
                if (next.has(s)) next.delete(s); else next.add(s);
                return next;
              })}><SpeakerBadge speaker={s} /></button>
            ))}
          </div>
        )}
      </div>
      <p className="muted small">Keys: <kbd>j</kbd>/<kbd>k</kbd> next/previous chunk · <kbd>space</kbd> play/pause · click a line to play from there.</p>

      <ol className="transcript">
        {chunks.map((c, i) => hiddenSpeakers.has(c.speaker) ? null : (
          <li key={c.id} ref={(el) => { if (el) rows.current.set(c.id, el); else rows.current.delete(c.id); }}
            className={`line s${c.speaker.replace(/\D+/g, "") || 0} ${i === currentIndex ? "current" : ""} ${i === playingIndex ? "playing" : ""}`}>
            <button className="line-time" onClick={() => playAt(i)} title="Play from here">
              {formatRange(c.start_time, c.end_time)}
            </button>
            <div className="line-body">
              <div className="line-head">
                <SpeakerBadge speaker={c.speaker} />
                <span className="muted small">#{c.chunk_index + 1}</span>
                <button className="link-btn small" onClick={() => copyLink(c.id)}>{copied === c.id ? "Copied" : "Copy link"}</button>
              </div>
              <p onClick={() => playAt(i)}><Highlight text={c.text} terms={terms} /></p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
