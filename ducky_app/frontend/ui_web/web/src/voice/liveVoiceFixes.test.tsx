// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { findWordRange, spokenWordAt } from "./TtsReadAlong";
import { qualifyVoiceModel, voiceModelAgent } from "./LiveVoicePickers";
import { orbStatusFor } from "./VoiceOverlay";

describe("read aloud on the formatted reply", () => {
  it("finds the spoken word in the rendered text, markdown marks ignored", () => {
    const spoken = "## Cause\nDucky saved **both** switches, both of them.";
    const at = spokenWordAt(spoken, spoken.indexOf("both of"));
    expect(at).toEqual({ word: "both", occurrence: 1 });
    const root = document.createElement("div");
    root.innerHTML = "<h2>Cause</h2><p>Ducky saved <strong>both</strong> switches, both of them.</p>";
    const range = findWordRange(root, at!.word, at!.occurrence);
    expect(range?.toString()).toBe("both");
    expect(range?.startContainer.parentElement?.tagName).toBe("P"); // the second "both", not the bold one
    expect(spokenWordAt("## heading", 0)).toBeNull(); // a bare markdown mark is not a word
  });
});

describe("live voice model", () => {
  const catalog = [{ id: "claude-sonnet-4-6", providerKey: "anthropic" }, { id: "gpt-6", providerKey: "openai" }];

  it("is saved with its backend, so a non-Cursor pick sticks", () => {
    expect(qualifyVoiceModel("claude-sonnet-4-6", "ducky", catalog)).toBe("anthropic:claude-sonnet-4-6");
    expect(qualifyVoiceModel("claude-haiku-5-5", "claude_code", catalog)).toBe("claude_code:claude-haiku-5-5");
    expect(qualifyVoiceModel("cursor:auto", "cursor", catalog)).toBe("cursor:auto");
    expect(qualifyVoiceModel("", "ducky", catalog)).toBe("");
  });

  it("reads back which agent a saved pick belongs to", () => {
    expect(voiceModelAgent("anthropic:claude-sonnet-4-6", catalog)).toBe("ducky");
    expect(voiceModelAgent("claude_code:claude-haiku-5-5", catalog)).toBe("claude_code");
    expect(voiceModelAgent("", catalog)).toBe("ducky");
  });
});

it("the voice bar's orb follows the live status", () => {
  expect(orbStatusFor("connecting")).toBe("thinking");
  expect(orbStatusFor("speaking")).toBe("speaking");
  expect(orbStatusFor("idle")).toBe("listening");
});
