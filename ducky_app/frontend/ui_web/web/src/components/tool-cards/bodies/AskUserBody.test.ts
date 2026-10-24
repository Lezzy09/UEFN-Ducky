import { describe, expect, it } from "vitest";
import { askUserError, rowsFromAskUser } from "./AskUserBody";

describe("AskUserBody rows", () => {
  it("summarizes selected labels and skipped answers", () => {
    const rows = rowsFromAskUser(
      {
        questions: [
          {
            id: "owner",
            prompt: "Who owns tables?",
            options: [
              { id: "plugin", label: "Plugin owns tables" },
              { id: "core", label: "Core owns tables" },
            ],
          },
          { id: "notes", prompt: "Notes?" },
        ],
      },
      JSON.stringify({
        ok: true,
        answers: {
          owner: { selected: ["plugin"], text: "", skipped: false },
          notes: { selected: [], text: "", skipped: true },
        },
      }),
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].summary).toBe("Plugin owns tables");
    expect(rows[0].status).toBe("answered");
    expect(rows[1].summary).toBe("Skipped");
    expect(rows[1].status).toBe("skipped");
  });

  it("reads answers wrapped by the tool server as {result: json}", () => {
    const inner = JSON.stringify({ ok: true, answers: { a: { selected: ["x"], text: "", skipped: false } } });
    const rows = rowsFromAskUser(
      { questions: [{ id: "a", prompt: "Path?", options: [{ id: "x", label: "Option X" }] }] },
      JSON.stringify({ result: inner }),
    );
    expect(rows).toEqual([{ id: "a", prompt: "Path?", summary: "Option X", status: "answered" }]);
  });

  it("shows waiting rows while the agent is paused", () => {
    const rows = rowsFromAskUser(
      {
        questions: [
          { id: "a", prompt: "Path A?" },
          { id: "b", prompt: "Path B?" },
        ],
      },
      "",
      { pending: true },
    );
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.status === "waiting")).toBe(true);
    expect(rows[0].summary).toBe("Waiting…");
  });

  it("a refused question says it was not asked and why, never Waiting", () => {
    // Oct 17 2026: the card said "failed" over "→ Waiting…" and hid the refusal.
    const why = "Call ducky_rename_self first with a 2–4 word task name, then retry this tool.";
    const rows = rowsFromAskUser({ questions: [{ id: "count_mode", prompt: "How should I count duckies?" }] }, why, {
      failed: true,
    });
    expect(rows).toEqual([{ id: "count_mode", prompt: "How should I count duckies?", summary: "Not asked", status: "failed" }]);
    expect(askUserError(why)).toBe(why);
    expect(askUserError(JSON.stringify({ ok: false, error: "No chat to ask in." }))).toBe("No chat to ask in.");
  });
});
