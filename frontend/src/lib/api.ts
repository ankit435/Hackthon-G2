import type {
  AnswerResponse, ChunkContext, EvaluationReport, FileSummary, IngestOutcome, SearchHit, SearchMode, Transcript,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const SEARCH_PATH: Record<SearchMode, string> = { hybrid: "/search", keyword: "/search/keyword", semantic: "/search/semantic" };

export const api = {
  search: (query: string, mode: SearchMode, topK: number) =>
    request<SearchHit[]>(`${SEARCH_PATH[mode]}?${new URLSearchParams({ query, top_k: String(topK) })}`),
  files: () => request<FileSummary[]>("/files"),
  transcript: (fileId: string) => request<Transcript>(`/files/${encodeURIComponent(fileId)}`),
  context: (chunkId: string, window: number) =>
    request<ChunkContext>(`/chunks/${encodeURIComponent(chunkId)}/context?window=${window}`),
  audioUrl: (fileId: string) => `/files/${encodeURIComponent(fileId)}/audio`,
  answer: (query: string, topK: number) =>
    request<AnswerResponse>("/answer", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, top_k: topK }),
    }),
  evaluation: () => request<EvaluationReport>("/evaluation"),
  config: () => request<Record<string, unknown>>("/config"),
};

/** Upload one or more files with byte-level progress (fetch cannot report upload progress; XHR can). */
export function uploadFiles(files: File[], onProgress: (fraction: number) => void): Promise<IngestOutcome[]> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/ingest/upload");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(body.outcomes as IngestOutcome[]);
        else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : xhr.statusText));
      } catch {
        reject(new ApiError(xhr.status, xhr.statusText || "invalid server response"));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network error: is the API running?"));
    xhr.send(form);
  });
}
