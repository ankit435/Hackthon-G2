export interface SearchHit {
  chunk_id: string;
  audio_file_id: string;
  file_name: string;
  file_path: string;
  speaker: string;
  text: string;
  start_time: number;
  end_time: number;
  language: string;
  score: number;
}

export interface FileSummary {
  id: string;
  file_name: string;
  language: string;
  language_probability: number;
  duration_seconds: number;
  created_at: string | null;
  chunk_count: number | null;
  speakers: string[] | null;
}

export interface ChunkOut {
  id: string;
  chunk_index: number;
  speaker: string;
  text: string;
  start_time: number;
  end_time: number;
  language: string;
  prev_chunk_id: string | null;
  next_chunk_id: string | null;
}

export interface Transcript {
  file: FileSummary;
  chunks: ChunkOut[];
}

export interface ChunkContext {
  file: FileSummary;
  before: ChunkOut[];
  chunk: ChunkOut;
  after: ChunkOut[];
}

export type IngestStatus = "ingested" | "skipped_existing" | "failed";

export interface IngestOutcome {
  path: string;
  status: IngestStatus;
  audio_file_id: string | null;
  chunk_count: number;
  duration_seconds: number | null;
  language: string | null;
  language_probability: number | null;
  stage: string | null;
  error_type: string | null;
  error: string | null;
  stage_seconds: Record<string, number>;
  chunking: Record<string, number>;
}

export interface Citation {
  number: number;
  chunk_id: string;
  audio_file_id: string;
  file_name: string;
  speaker: string;
  start_time: number;
  end_time: number;
  language: string;
  text: string;
}

export interface AnswerResponse {
  answer: string;
  citations: Citation[];
}

export type MetricGroup = Record<string, number>;

export interface EvaluationReport {
  config: Record<string, unknown>;
  summary: {
    config?: Record<string, unknown>;
    fused?: Record<string, MetricGroup>;
    keyword_branch_only?: Record<string, MetricGroup>;
    semantic_branch_only?: Record<string, MetricGroup>;
    speaker_accuracy?: { accuracy: number | null; judged_results: number; unjudged_results: number };
    latency_ms?: Record<string, number>;
    [key: string]: unknown;
  };
}

export type SearchMode = "hybrid" | "keyword" | "semantic";
