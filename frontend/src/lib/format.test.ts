import { describe, expect, it } from "vitest";
import { activeChunkIndex, formatBytes, formatRange, formatTime, languageName, speakerLabel, speakerSlot } from "./format";

describe("formatTime", () => {
  it.each([[0, "0:00"], [5.9, "0:05"], [75.4, "1:15"], [3725, "1:02:05"], [-3, "0:00"], [Number.NaN, "0:00"]])(
    "%s -> %s", (s, out) => expect(formatTime(s)).toBe(out));
  it("formats ranges", () => expect(formatRange(61, 125)).toBe("1:01 – 2:05"));
});

describe("speakers and languages", () => {
  it("maps speaker ids to stable colour slots and 1-based labels", () => {
    expect(speakerSlot("SPEAKER_00")).toBe(0);
    expect(speakerSlot("SPEAKER_07")).toBe(1);
    expect(speakerLabel("SPEAKER_01")).toBe("Speaker 2");
    expect(speakerLabel("host")).toBe("host");
  });
  it("names known languages and falls back to the code", () => {
    expect(languageName("hi")).toBe("Hindi");
    expect(languageName("sw")).toBe("SW");
  });
});

describe("activeChunkIndex", () => {
  const chunks = [{ start_time: 0, end_time: 4 }, { start_time: 4.2, end_time: 9 }, { start_time: 9.5, end_time: 12 }];
  it.each([[-1, -1], [0, 0], [3.9, 0], [4.1, 0], [4.2, 1], [9.2, 1], [9.5, 2], [99, 2]])("t=%s -> %s", (t, i) =>
    expect(activeChunkIndex(chunks, t)).toBe(i));
  it("handles an empty transcript", () => expect(activeChunkIndex([], 5)).toBe(-1));
});

it("formats byte sizes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(16646552)).toBe("15.9 MB");
});
