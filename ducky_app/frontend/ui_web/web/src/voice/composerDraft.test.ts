import { describe, expect, it } from "vitest";

import { beginDraft, joinWords, renderDraft } from "./composerDraft";

describe("joinWords", () => {
  it("adds one space between runs", () => {
    expect(joinWords("hello", "world")).toBe("hello world");
    expect(joinWords("hello ", "world")).toBe("hello world");
    expect(joinWords("", "world")).toBe("world");
    expect(joinWords("hello", "")).toBe("hello");
  });
});

describe("renderDraft", () => {
  it("streams interim words, then confirms them after the existing text", () => {
    const d = beginDraft("Fix the");
    d.interim = "spawn";
    let box = renderDraft(d, "Fix the");
    expect(box).toBe("Fix the spawn");
    d.interim = "spawn pads";
    box = renderDraft(d, box);
    expect(box).toBe("Fix the spawn pads");
    d.spoken = joinWords(d.spoken, "spawn pads please");
    d.interim = "";
    box = renderDraft(d, box);
    expect(box).toBe("Fix the spawn pads please");
  });

  it("keeps a user edit made mid-dictation and drops the stale interim", () => {
    const d = beginDraft("");
    d.spoken = "make a door";
    d.interim = "that opens";
    const box = renderDraft(d, "");
    expect(box).toBe("make a door that opens");
    // User types a period before the next recognition event lands.
    const edited = "Make a door. that opens";
    d.interim = "that opens slowly";
    expect(renderDraft(d, edited)).toBe("Make a door. that opens slowly");
  });

  it("starts fresh after the box is cleared by Send", () => {
    const d = beginDraft("");
    d.spoken = "first turn";
    renderDraft(d, "");
    d.interim = "second";
    expect(renderDraft(d, "")).toBe("second");
  });
});
