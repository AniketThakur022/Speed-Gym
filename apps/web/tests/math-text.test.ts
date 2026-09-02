import { describe, expect, it } from "vitest";
import { segment } from "../src/components/math-text";

/**
 * The render contract (docs/rag/LATEX_RENDER_CONTRACT.md) turns on one
 * distinction: prose-with-inline-math must be segmented, while a raw math-mode
 * field must NOT be — passing a delimiter-free formula through the prose path
 * renders it as plain text, silently. These tests pin the segmenter's half of
 * that; the math path deliberately bypasses it entirely.
 */
describe("prose segmentation", () => {
  it("splits inline $…$ from surrounding prose", () => {
    const parts = segment("Determine $735 + 167$ exactly");
    expect(parts.map((p) => p.type)).toEqual(["text", "math", "text"]);
    expect(parts[1].value).toBe("735 + 167");
    expect(parts[1].display).toBe(false);
  });

  it("treats \\[…\\] and $$…$$ as display math", () => {
    expect(segment("\\[x = 1\\]")[0].display).toBe(true);
    expect(segment("$$x = 1$$")[0].display).toBe(true);
  });

  it("handles \\(…\\) inline delimiters", () => {
    const parts = segment("value \\(a+b\\) here");
    expect(parts[1]).toMatchObject({ type: "math", value: "a+b", display: false });
  });

  it("keeps multiple math runs separate", () => {
    const parts = segment("$a$ and $b$");
    expect(parts.filter((p) => p.type === "math").map((p) => p.value)).toEqual(["a", "b"]);
  });

  it("returns plain prose as a single text run", () => {
    const parts = segment("no math at all");
    expect(parts).toEqual([{ type: "text", value: "no math at all", display: false }]);
  });

  it("leaves a delimiter-free formula as TEXT — which is why math mode exists", () => {
    // "5 \times 7 = 35" is the contract's raw math-mode shape. The prose path
    // cannot render it, so `result` fields must use mode="math".
    const parts = segment("5 \\times 7 = 35");
    expect(parts).toHaveLength(1);
    expect(parts[0].type).toBe("text");
  });

  it("handles an empty string without producing a run", () => {
    expect(segment("")).toEqual([]);
  });
});
