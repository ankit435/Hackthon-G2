import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IngestJob, IngestOutcome } from "../lib/types";
import { UploadPage } from "./UploadPage";

const uploadFiles = vi.fn();
const jobs = vi.fn();
const cancelJob = vi.fn();
vi.mock("../lib/api", async (orig) => {
  const real = await orig<typeof import("../lib/api")>();
  return {
    ...real,
    uploadFiles: (...a: unknown[]) => uploadFiles(...a),
    api: { ...real.api, jobs: () => jobs(), cancelJob: (id: string) => cancelJob(id) },
  };
});

const outcome = (over: Partial<IngestOutcome>): IngestOutcome => ({
  path: "", status: "ingested", audio_file_id: "f1", chunk_count: 12, duration_seconds: 125, language: "hi",
  language_probability: 0.98, stage: null, error_type: null, error: null, stage_seconds: { transcribe: 40.2 }, chunking: {}, ...over,
});
const job = (over: Partial<IngestJob>): IngestJob => ({
  id: "j1", file_name: "one.wav", state: "queued", stage: null, position: 1, created_at: 1, started_at: null,
  finished_at: null, outcome: null, ...over,
});

describe("UploadPage", () => {
  beforeEach(() => { uploadFiles.mockReset(); jobs.mockReset(); cancelJob.mockReset(); });

  it("uploads each file separately, then follows the queue until every job finishes", async () => {
    jobs.mockResolvedValueOnce([]); // page load
    uploadFiles
      .mockImplementationOnce(async (_f: File[], progress: (x: number) => void) => { progress(1); return [job({})]; })
      .mockImplementationOnce(async () => [job({ id: "j2", file_name: "two.mp3", position: 2, created_at: 2 })]);
    // The worker runs one job at a time: one.wav first while two.mp3 waits, then the final state.
    jobs.mockResolvedValueOnce([
      job({ state: "running", stage: "embed", position: null, started_at: 10 }),
      job({ id: "j2", file_name: "two.mp3", position: 1, created_at: 2 }),
    ]);
    jobs.mockResolvedValue([
      job({ state: "ingested", position: null, started_at: 10, finished_at: 50, outcome: outcome({}) }),
      job({ id: "j2", file_name: "two.mp3", state: "failed", position: null, created_at: 2, started_at: 50, finished_at: 51,
        outcome: outcome({ status: "failed", audio_file_id: null, stage: "transcribe", error: "bad audio" }) }),
    ]);
    render(<MemoryRouter><UploadPage pollMs={30} /></MemoryRouter>);
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    await userEvent.upload(input, [new File(["a"], "one.wav", { type: "audio/wav" }), new File(["b"], "two.mp3", { type: "audio/mpeg" })]);
    await userEvent.click(screen.getByRole("button", { name: "Upload 2 files" }));

    const queue = screen.getByRole("region", { name: "Processing queue" });
    expect(await within(queue).findByText("Processing · embed")).toBeInTheDocument();
    expect(within(queue).getByText("#1")).toBeInTheDocument(); // two.mp3 is next in line
    expect(within(queue).getByText("embed")).toHaveAttribute("aria-current", "step");

    const one = (await within(queue).findByText("Indexed")).closest("li")!;
    expect(within(one).getByText("12 chunks")).toBeInTheDocument();
    expect(within(one).getByText("Hindi")).toBeInTheDocument();
    expect(within(one).getByRole("link", { name: "Open transcript →" })).toHaveAttribute("href", "/files/f1");
    const two = within(queue).getByText("two.mp3").closest("li")!;
    expect(within(two).getByText("transcribe: bad audio")).toBeInTheDocument();
    expect(uploadFiles.mock.calls.map((c) => (c[0] as File[]).map((f) => f.name))).toEqual([["one.wav"], ["two.mp3"]]);
    expect(screen.queryByRole("list", { name: "Files to upload" })).not.toBeInTheDocument(); // both handed to the queue
  });

  it("cancels a queued job", async () => {
    jobs.mockResolvedValue([job({ state: "running", stage: "decode", position: null, started_at: 1 }),
      job({ id: "j2", file_name: "two.mp3", created_at: 2 })]);
    cancelJob.mockResolvedValue(job({ id: "j2", file_name: "two.mp3", state: "cancelled", position: null, created_at: 2 }));
    render(<MemoryRouter><UploadPage pollMs={60_000} /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel two.mp3" }));
    expect(cancelJob).toHaveBeenCalledWith("j2");
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
  });
});
