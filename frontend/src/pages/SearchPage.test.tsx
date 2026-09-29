import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlayerProvider } from "../lib/player";
import { SearchPage } from "./SearchPage";

const hit = {
  chunk_id: "c1", audio_file_id: "f1", file_name: "rate_limiter.wav", file_path: "/x.wav", speaker: "SPEAKER_01",
  text: "A token bucket holds a maximum number of tokens.", start_time: 75, end_time: 84.5, language: "en", score: 0.0328,
};

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <PlayerProvider><Routes><Route path="/search" element={<SearchPage />} /></Routes></PlayerProvider>
    </MemoryRouter>,
  );
}

describe("SearchPage", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(JSON.stringify([hit]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("searches from the URL and shows file, time, speaker, language and highlighted text", async () => {
    renderAt("/search?q=token%20bucket&mode=hybrid&k=10");
    expect(await screen.findByText("rate_limiter.wav")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/search?query=token+bucket&top_k=10", undefined);
    expect(screen.getByText("1:15 – 1:24")).toBeInTheDocument();
    expect(screen.getByText("Speaker 2")).toBeInTheDocument();
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getAllByText(/token/i, { selector: "mark" }).length).toBeGreaterThan(0);
  });

  it("uses the diagnostic endpoint for the chosen mode", async () => {
    renderAt("/search?q=idempotency&mode=keyword&k=5");
    await screen.findByText("rate_limiter.wav");
    expect(fetchMock).toHaveBeenCalledWith("/search/keyword?query=idempotency&top_k=5", undefined);
  });

  it("submits a typed query and shows server errors", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "query must not be empty" }), { status: 400 }));
    renderAt("/search");
    await userEvent.type(screen.getByLabelText("Search query"), "hello{enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("query must not be empty");
  });

  it("opens the context of a hit on demand", async () => {
    renderAt("/search?q=token");
    await screen.findByText("rate_limiter.wav");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      file: { id: "f1", file_name: "rate_limiter.wav", language: "en", language_probability: 1, duration_seconds: 400, created_at: null, chunk_count: null, speakers: null },
      before: [{ ...hit, id: "c0", chunk_index: 0, text: "Before it.", prev_chunk_id: null, next_chunk_id: "c1" }],
      chunk: { ...hit, id: "c1", chunk_index: 1, prev_chunk_id: "c0", next_chunk_id: null },
      after: [],
    }), { status: 200 }));
    await userEvent.click(screen.getByRole("button", { name: "Show context" }));
    expect(await screen.findByText("Before it.")).toBeInTheDocument();
    expect(screen.getByText("End of recording")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith("/chunks/c1/context?window=2", undefined));
  });
});
