import { useState } from "react";
import { Link } from "react-router-dom";
import { formatRange } from "../lib/format";
import { usePlayer } from "../lib/player";
import type { SearchHit } from "../lib/types";
import { ContextPanel } from "./ContextPanel";
import { Highlight, LanguageBadge, PlayIcon, SpeakerBadge } from "./common";

export function HitCard({ hit, rank, terms }: { hit: SearchHit; rank: number; terms: string[] }) {
  const [showContext, setShowContext] = useState(false);
  const player = usePlayer();
  const isPlaying = player.playing && player.track?.fileId === hit.audio_file_id &&
    player.time >= hit.start_time && player.time <= hit.end_time;

  return (
    <article className={`hit ${isPlaying ? "playing" : ""}`}>
      <div className="hit-rank">{rank}</div>
      <div className="hit-body">
        <header className="hit-head">
          <Link to={`/files/${hit.audio_file_id}?chunk=${hit.chunk_id}`} className="hit-file">{hit.file_name}</Link>
          <span className="time">{formatRange(hit.start_time, hit.end_time)}</span>
          <SpeakerBadge speaker={hit.speaker} />
          <LanguageBadge code={hit.language} />
          <span className="score" title="Ranking score (fused RRF, branch score, or re-ranker relevance)">
            {hit.score.toFixed(4)}
          </span>
        </header>
        <p className="hit-text"><Highlight text={hit.text} terms={terms} /></p>
        <div className="hit-actions">
          <button className="btn small" onClick={() => player.play(
            { fileId: hit.audio_file_id, fileName: hit.file_name }, hit.start_time, hit.end_time)}>
            <PlayIcon playing={isPlaying} /> Play segment
          </button>
          <button className="btn small ghost" onClick={() => setShowContext((v) => !v)} aria-expanded={showContext}>
            {showContext ? "Hide context" : "Show context"}
          </button>
          <Link className="btn small ghost" to={`/files/${hit.audio_file_id}?chunk=${hit.chunk_id}`}>Transcript</Link>
        </div>
        {showContext && <ContextPanel chunkId={hit.chunk_id} />}
      </div>
    </article>
  );
}
