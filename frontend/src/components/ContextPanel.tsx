import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { formatRange } from "../lib/format";
import { usePlayer } from "../lib/player";
import type { ChunkContext, ChunkOut } from "../lib/types";
import { ErrorBox, PlayIcon, SpeakerBadge, Spinner } from "./common";

/** A chunk with its neighbours, fetched on demand: what was said just before and after a search hit. */
export function ContextPanel({ chunkId }: { chunkId: string }) {
  const [size, setSize] = useState(2);
  const [data, setData] = useState<ChunkContext | null>(null);
  const [error, setError] = useState<unknown>(null);
  const player = usePlayer();

  useEffect(() => {
    let live = true;
    setError(null);
    api.context(chunkId, size).then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [chunkId, size]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Spinner label="Loading context" />;

  const row = (c: ChunkOut, current: boolean) => (
    <li key={c.id} className={`context-row ${current ? "current" : ""}`}>
      <button className="icon-btn small" aria-label={`Play ${formatRange(c.start_time, c.end_time)}`}
        onClick={() => player.play({ fileId: data.file.id, fileName: data.file.file_name }, c.start_time, c.end_time)}>
        <PlayIcon />
      </button>
      <span className="time">{formatRange(c.start_time, c.end_time)}</span>
      <SpeakerBadge speaker={c.speaker} />
      <p>{c.text}</p>
    </li>
  );

  return (
    <div className="context-panel">
      <div className="context-head">
        <span className="muted">Context · chunk {data.chunk.chunk_index + 1}</span>
        <label className="inline">
          Neighbours
          <select value={size} onChange={(e) => setSize(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <Link to={`/files/${data.file.id}?chunk=${data.chunk.id}`} className="link">Open full transcript →</Link>
      </div>
      <ol className="context-list">
        {data.before.length === 0 && <li className="edge muted">Start of recording</li>}
        {data.before.map((c) => row(c, false))}
        {row(data.chunk, true)}
        {data.after.map((c) => row(c, false))}
        {data.after.length === 0 && <li className="edge muted">End of recording</li>}
      </ol>
    </div>
  );
}
