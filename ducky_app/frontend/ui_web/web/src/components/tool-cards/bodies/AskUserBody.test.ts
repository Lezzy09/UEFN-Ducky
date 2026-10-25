// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

// One array: useSyncExternalStore loops forever when the snapshot is a new object each read.
const noModels = vi.hoisted(() => [] as never[]);
vi.mock("../../../hooks/modelsCatalogCache", () => ({
  getCachedModels: () => noModels,
  loadModelsCatalog: async () => [],
  subscribeModelsCatalog: () => () => {},
}));
import fixture from "../../../swarm/fixtures/swarm_builder.json";
import { AskUserBody, askUserError, rowsFromAskUser } from "./AskUserBody";

afterEach(cleanup);

describe("AskUserBody picks the card", () => {
  const base = { toolName: "ducky_ask_user", showResult: false, isError: false } as Record<string, unknown>;

  it("a ui: swarm_builder payload renders the Swarm builder card", () => {
    render(createElement(AskUserBody as never, { ...base, args: { ...fixture, jobs: [] }, resultText: "" }));
    expect(screen.getByText("Build swarm: Shop island")).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Detail" })).toBeTruthy();
  });

  it("an old question payload still renders its question rows", () => {
    render(createElement(AskUserBody as never, { ...base, args: { questions: [{ id: "a", prompt: "Path A?" }] }, resultText: "" }));
    expect(screen.getByText("Path A?")).toBeTruthy();
    expect(screen.queryByText(/^Build swarm/)).toBeNull();
  });
});

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
