import { describe, expect, it } from "vitest";
import { clampLogHeight } from "./AutomationsView";
import { formatRunLog, runLogHasContent } from "./runLog";

describe("clampLogHeight", () => {
  it("keeps the dock between 140 and the board", () => {
    expect(clampLogHeight(80)).toBe(140);
    expect(clampLogHeight(900)).toBe(560);
    expect(clampLogHeight(400, 200)).toBe(176);
  });
});

describe("formatRunLog", () => {
  it("copies name, status, and each step", () => {
    const text = formatRunLog(
      {
        ok: false,
        error: "listener offline",
        steps: [
          { label: "Chat", ok: true },
          { label: "Start game", ok: false, error: "UEFN listener not found" },
        ],
      },
      "Playtest a mechanic",
    );
    expect(text).toBe(
      [
        "Playtest a mechanic",
        "Failed: listener offline",
        "1. Chat ok",
        "2. Start game — UEFN listener not found",
      ].join("\n"),
    );
    expect(runLogHasContent({ ok: false, error: "x" })).toBe(true);
    expect(formatRunLog({ ok: true, outputs: { greeting: "Hi", n: 2 }, steps: [
      { label: "Greeter", ok: true, substeps: [{ label: "Inputs", ok: true }, { label: "Tool", ok: false, error: "boom" }] },
    ] })).toBe(["Finished", "1. Greeter ok", "1.1. Inputs ok", "1.2. Tool — boom", "Returned: greeting = Hi, n = 2"].join("\n"));
    expect(runLogHasContent({ steps: [] })).toBe(false);
  });
});
