import { Fragment, type ReactNode } from "react";
import { languageName, speakerLabel, speakerSlot } from "../lib/format";

export function SpeakerBadge({ speaker }: { speaker: string }) {
  return <span className={`badge speaker s${speakerSlot(speaker)}`} title={speaker}>{speakerLabel(speaker)}</span>;
}

export function LanguageBadge({ code }: { code: string }) {
  return <span className="badge lang" title={code}>{languageName(code)}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label ?? "loading"}><span />{label}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <div className="error-box" role="alert">{message}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function PlayIcon({ playing = false }: { playing?: boolean }) {
  return playing ? (
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
  ) : (
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" /></svg>
  );
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Terms to highlight for a query: whitespace-separated words (>= 2 chars), or the whole query for CJK/unspaced text. */
export function highlightTerms(query: string): string[] {
  const q = query.trim().replace(/["']/g, "");
  if (!q) return [];
  const words = q.split(/\s+/).filter((w) => w.length >= 2 && !/^(or|and|the|a|an|of|to|in|is|-.*)$/i.test(w));
  return words.length ? words : [q];
}

/** Renders `text` with case-insensitive matches of `terms` wrapped in <mark>. Pure string matching; no HTML injection. */
export function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const re = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "giu");
  const parts = text.split(re);
  return <>{parts.map((p, i) => (i % 2 === 1 ? <mark key={i}>{p}</mark> : <Fragment key={i}>{p}</Fragment>))}</>;
}
