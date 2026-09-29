/** 75.4 -> "1:15", 3725 -> "1:02:05". Negative or non-finite input renders as "0:00". */
export function formatTime(seconds: number): string {
  const s = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function formatRange(start: number, end: number): string {
  return `${formatTime(start)} – ${formatTime(end)}`;
}

const LANGUAGES: Record<string, string> = {
  en: "English", es: "Spanish", hi: "Hindi", zh: "Chinese", fr: "French", de: "German", ja: "Japanese",
  ko: "Korean", pt: "Portuguese", it: "Italian", ru: "Russian", ar: "Arabic", nl: "Dutch", tr: "Turkish",
};

export function languageName(code: string): string {
  return LANGUAGES[code] ?? code.toUpperCase();
}

/** Stable speaker colour slot: SPEAKER_00 -> 0, SPEAKER_01 -> 1, ... (cycled over 6 slots). */
export function speakerSlot(speaker: string): number {
  const n = Number.parseInt(speaker.replace(/\D+/g, ""), 10);
  return Number.isFinite(n) ? n % 6 : 0;
}

export function speakerLabel(speaker: string): string {
  const n = Number.parseInt(speaker.replace(/\D+/g, ""), 10);
  return Number.isFinite(n) ? `Speaker ${n + 1}` : speaker;
}

/** Index of the chunk that contains time t (chunks sorted by start); falls back to the last chunk started. */
export function activeChunkIndex(chunks: { start_time: number; end_time: number }[], t: number): number {
  let lo = 0, hi = chunks.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (chunks[mid].start_time <= t) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
