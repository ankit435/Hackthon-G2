import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

export interface Track {
  fileId: string;
  fileName: string;
}

interface PlayerValue {
  track: Track | null;
  playing: boolean;
  time: number;
  duration: number;
  segmentEnd: number | null;
  error: string | null;
  /** Play `track` from `start`; if `end` is given, pause there (segment playback). */
  play: (track: Track, start: number, end?: number) => void;
  toggle: () => void;
  seek: (t: number) => void;
  stop: () => void;
}

const PlayerContext = createContext<PlayerValue | null>(null);

export function usePlayer(): PlayerValue {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer must be used inside <PlayerProvider>");
  return value;
}

/** One <audio> element for the whole app, so every result, transcript line and citation shares the player. */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [segmentEnd, setSegmentEnd] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<number | null>(null);

  const start = useCallback((el: HTMLAudioElement, at: number) => {
    el.currentTime = at;
    el.play().catch((e: unknown) => setError(e instanceof Error ? e.message : "playback failed"));
  }, []);

  const play = useCallback((next: Track, at: number, end?: number) => {
    const el = audio.current;
    if (!el) return;
    setError(null);
    endRef.current = end ?? null;
    setSegmentEnd(end ?? null);
    const src = api.audioUrl(next.fileId);
    if (!el.src.endsWith(src)) {
      setTrack(next);
      el.src = src;
      el.addEventListener("loadedmetadata", () => start(el, at), { once: true });
      el.load();
    } else {
      start(el, at);
    }
  }, [start]);

  const toggle = useCallback(() => {
    const el = audio.current;
    if (!el || !el.src) return;
    if (el.paused) {
      endRef.current = null; // resuming plays on past a finished segment
      setSegmentEnd(null);
      el.play().catch(() => undefined);
    } else el.pause();
  }, []);

  const seek = useCallback((t: number) => {
    if (audio.current) audio.current.currentTime = t;
  }, []);

  const stop = useCallback(() => {
    const el = audio.current;
    if (!el) return;
    el.pause();
    el.removeAttribute("src");
    el.load();
    setTrack(null);
    setTime(0);
    setDuration(0);
  }, []);

  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    const onTime = () => {
      setTime(el.currentTime);
      if (endRef.current !== null && el.currentTime >= endRef.current) {
        el.pause();
        endRef.current = null;
        setSegmentEnd(null);
      }
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onMeta = () => setDuration(el.duration || 0);
    const onError = () => setError("could not load audio (is the file still on disk?)");
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("loadedmetadata", onMeta);
    el.addEventListener("error", onError);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("loadedmetadata", onMeta);
      el.removeEventListener("error", onError);
    };
  }, []);

  const value = useMemo(() => ({ track, playing, time, duration, segmentEnd, error, play, toggle, seek, stop }),
    [track, playing, time, duration, segmentEnd, error, play, toggle, seek, stop]);

  return (
    <PlayerContext.Provider value={value}>
      {children}
      <audio ref={audio} preload="metadata" hidden />
    </PlayerContext.Provider>
  );
}
