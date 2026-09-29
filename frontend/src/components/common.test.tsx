import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Highlight, highlightTerms } from "./common";

describe("highlightTerms", () => {
  it("splits words and drops short/stop words", () => expect(highlightTerms("the token bucket a")).toEqual(["token", "bucket"]));
  it("keeps an unspaced CJK query whole", () => expect(highlightTerms("限流器")).toEqual(["限流器"]));
  it("is empty for a blank query", () => expect(highlightTerms("   ")).toEqual([]));
});

describe("Highlight", () => {
  it("wraps case-insensitive matches in <mark>", () => {
    const { container } = render(<Highlight text="Token bucket and TOKEN refill" terms={["token"]} />);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["Token", "TOKEN"]);
    expect(container.textContent).toBe("Token bucket and TOKEN refill");
  });
  it("treats regex characters in the query literally and never injects HTML", () => {
    const { container } = render(<Highlight text="a+b <b>bold</b> (x)" terms={["a+b", "(x)", "<b>"]} />);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["a+b", "<b>", "(x)"]);
    expect(container.querySelector("b")).toBeNull();
  });
});
