import { speakerLabel, speakerSlot } from "../lib/format";

/** Animated equaliser bars; frozen when not playing. Purely decorative. */
export function EqBars({ playing }: { playing: boolean }) {
  return (
    <span className={`eq ${playing ? "on" : ""}`} aria-hidden="true">
      <i /><i /><i /><i />
    </span>
  );
}

interface Span { id: string; speaker: string; start_time: number; end_time: number }

/** Speaker timeline for a whole recording: one coloured block per chunk, a playhead, click to seek. */
export function Timeline({ spans, duration, time, activeId, onSeek }: {
  spans: Span[]; duration: number; time: number | null; activeId?: string | null; onSeek: (t: number) => void;
}) {
  if (!duration) return null;
  const speakers = [...new Set(spans.map((s) => s.speaker))].sort();
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  return (
    <div className="timeline">
      <div className="timeline-lanes" role="slider" aria-label="Recording timeline" aria-valuemin={0}
        aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(time ?? 0)} tabIndex={0}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - r.left) / r.width) * duration);
        }}>
        {speakers.map((sp) => (
          <div key={sp} className="lane">
            {spans.filter((s) => s.speaker === sp).map((s) => (
              <span key={s.id} className={`block s${speakerSlot(s.speaker)} ${s.id === activeId ? "active" : ""}`}
                style={{ left: pct(s.start_time), width: pct(s.end_time - s.start_time) }} />
            ))}
          </div>
        ))}
        {time !== null && <span className="playhead" style={{ left: pct(time) }} />}
      </div>
      <div className="timeline-legend">
        {speakers.map((sp) => <span key={sp} className={`legend s${speakerSlot(sp)}`}>{speakerLabel(sp)}</span>)}
      </div>
    </div>
  );
}

/** Where a hit sits inside its recording (a tiny position bar). */
export function PositionBar({ start, end, duration }: { start: number; end: number; duration?: number }) {
  if (!duration) return null;
  return (
    <span className="posbar" title="Position in the recording">
      <span style={{ left: `${(start / duration) * 100}%`, width: `${Math.max(1.5, ((end - start) / duration) * 100)}%` }} />
    </span>
  );
}
