import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { IngestOutcome } from "../lib/types";
import { UploadPage } from "./UploadPage";

const uploadFiles = vi.fn();
vi.mock("../lib/api", async (orig) => ({ ...(await orig<typeof import("../lib/api")>()), uploadFiles: (...a: unknown[]) => uploadFiles(...a) }));

const outcome = (over: Partial<IngestOutcome>): IngestOutcome => ({
  path: "", status: "ingested", audio_file_id: "f1", chunk_count: 12, duration_seconds: 125, language: "hi",
  language_probability: 0.98, stage: null, error_type: null, error: null, stage_seconds: { transcribe: 40.2 }, chunking: {}, ...over,
});

describe("UploadPage", () => {
  it("uploads each file separately and shows every outcome, including a failure", async () => {
    uploadFiles
      .mockImplementationOnce(async (_f: File[], progress: (x: number) => void) => { progress(1); return [outcome({})]; })
      .mockImplementationOnce(async () => [outcome({ status: "failed", audio_file_id: null, stage: "transcribe", error: "bad audio" })]);
    render(<MemoryRouter><UploadPage /></MemoryRouter>);
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    await userEvent.upload(input, [new File(["a"], "one.wav", { type: "audio/wav" }), new File(["b"], "two.mp3", { type: "audio/mpeg" })]);
    await userEvent.click(screen.getByRole("button", { name: "Upload & index 2 files" }));

    const one = (await screen.findByText("one.wav")).closest("li")!;
    expect(await within(one).findByText("Indexed")).toBeInTheDocument();
    expect(within(one).getByText("12 chunks")).toBeInTheDocument();
    expect(within(one).getByText("Hindi")).toBeInTheDocument();
    expect(within(one).getByRole("link", { name: "Open transcript →" })).toHaveAttribute("href", "/files/f1");

    const two = screen.getByText("two.mp3").closest("li")!;
    expect(await within(two).findByText("Failed")).toBeInTheDocument();
    expect(within(two).getByText("transcribe: bad audio")).toBeInTheDocument();
    expect(uploadFiles).toHaveBeenCalledTimes(2);
    expect(uploadFiles.mock.calls.map((c) => (c[0] as File[]).map((f) => f.name))).toEqual([["one.wav"], ["two.mp3"]]);
  });
});
