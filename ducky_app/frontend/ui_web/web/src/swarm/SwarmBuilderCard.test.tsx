// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/swarm_builder.json";

const api = vi.hoisted(() => ({ swarm_preview: vi.fn(), plan_progress: vi.fn() }));
const bus = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
// One array: useSyncExternalStore loops forever when the snapshot is a new object each read.
const noModels = vi.hoisted(() => [] as never[]);
vi.mock("../hooks/modelsCatalogCache", () => ({
  getCachedModels: () => noModels,
  loadModelsCatalog: async () => [],
  subscribeModelsCatalog: () => () => {},
}));
vi.mock("../hooks/useAgentEventBus", () => ({
  subscribeAgentEvents: (fn: (event: Record<string, unknown>) => void) => {
    bus.handlers.add(fn);
    return () => bus.handlers.delete(fn);
  },
}));

import {
  SWARM_PREVIEW_DEBOUNCE_MS,
  SwarmBuilderCard,
  SwarmBuilderToolView,
  nextSeatState,
  swarmBuilderPayload,
} from "./SwarmBuilderCard";
import { SwarmCard } from "../components/tool-presenters/SwarmCard";
import { resolveToolPresenterView } from "../components/tool-presenters/resolveToolPresenter";

const JOBS = [{ name: "Modeling: props" }, { name: "Verse: shop logic" }];

function emit(event: Record<string, unknown>) {
  act(() => {
    for (const fn of [...bus.handlers]) fn(event);
  });
}

beforeEach(() => {
  api.swarm_preview.mockReset();
  api.plan_progress.mockReset();
  api.plan_progress.mockResolvedValue({ ok: true, progress: {} });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  bus.handlers.clear();
});

describe("SwarmBuilderCard from the swarm_builder payload", () => {
  it("renders the fixture: title, three sliders, counts, the seat tree and one editor per seat and group", () => {
    const { container } = render(<SwarmBuilderCard payload={fixture} jobs={JOBS} />);
    expect(screen.getByText("Build swarm: Shop island")).toBeTruthy();
    expect((screen.getByRole("slider", { name: "Detail" }) as HTMLInputElement).value).toBe("2");
    expect((screen.getByRole("slider", { name: "Max agents" }) as HTMLInputElement).value).toBe("8");
    expect((screen.getByRole("slider", { name: "Per group" }) as HTMLInputElement).value).toBe("5");
    expect(screen.getByText("6 agents · 2 groups")).toBeTruthy();
    expect(screen.getByLabelText("Swarm tree")).toBeTruthy();
    expect(container.querySelectorAll(".swarm-seat-editor")).toHaveLength(6);
    expect(container.querySelectorAll(".swarm-group-editor")).toHaveLength(2);
    expect((screen.getByRole("button", { name: "Build" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("styles SwarmTree's seat rows: one per seat with its name and model chip", () => {
    const { container } = render(<SwarmBuilderCard payload={fixture} jobs={JOBS} />);
    const rows = [...container.querySelectorAll("li.swarm-tree-seat")];
    expect(rows.map((r) => r.querySelector(".swarm-tree-seat-name")?.textContent)).toEqual([
      "Narrative lead", "Tester", "Modeling lead", "Texture lead", "Verse lead", "UI lead",
    ]);
    expect(rows[2].querySelector(".swarm-tree-model-chip")?.textContent).toBe("Sonnet 5.5");
    expect(rows[4].querySelector(".swarm-tree-model-chip")?.textContent).toBe("Opus 5.5");
    expect(container.querySelectorAll(".swarm-tree-node--overlap")).toHaveLength(0);
  });

  it("finds the payload in text, {result: json} and {data} wrappers; a plain question is not one", () => {
    expect(swarmBuilderPayload(JSON.stringify(fixture))?.goal).toBe("Shop island");
    expect(swarmBuilderPayload({ result: JSON.stringify(fixture) })?.goal).toBe("Shop island");
    expect(swarmBuilderPayload({ ok: true, data: fixture })?.goal).toBe("Shop island");
    expect(swarmBuilderPayload({ questions: [{ id: "a", prompt: "Path?" }] })).toBeNull();
    expect(swarmBuilderPayload("not json")).toBeNull();
  });

  it("ducky_swarm_create: needs_answers draws the builder; needs_confirm keeps SwarmCard", () => {
    const asking = JSON.stringify({ ...fixture, status: "needs_answers" });
    expect(resolveToolPresenterView("mcp__uefn__ducky_swarm_create", asking)).toBe(SwarmBuilderToolView);
    expect(resolveToolPresenterView("ducky_swarm_create", JSON.stringify(fixture))).toBe(SwarmCard);
    expect(resolveToolPresenterView("ducky_swarm_create", JSON.stringify({ status: "needs_answers" }))).toBeNull();
  });
});

describe("SwarmBuilderCard sliders", () => {
  it("detail 2→3 shows that level's counts at once, then one swarm_preview after 120 ms", async () => {
    vi.useFakeTimers();
    const next = { ...fixture, preview: { ...fixture.preview, detail: 3, agents: 8 } };
    api.swarm_preview.mockResolvedValue({ ok: true, ...next });
    render(<SwarmBuilderCard payload={fixture} jobs={JOBS} />);
    const detail = screen.getByRole("slider", { name: "Detail" });

    fireEvent.change(detail, { target: { value: "4" } });
    fireEvent.change(detail, { target: { value: "3" } });
    const level3 = fixture.preview.levels[2];
    expect(screen.getByText(`${level3.agents} agents · ${level3.groups} groups`)).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Detail" }).getAttribute("aria-valuetext")).toBe("Parts");
    expect(api.swarm_preview).not.toHaveBeenCalled();

    await act(async () => void (await vi.advanceTimersByTimeAsync(SWARM_PREVIEW_DEBOUNCE_MS)));
    expect(api.swarm_preview).toHaveBeenCalledTimes(1);
    expect(api.swarm_preview).toHaveBeenCalledWith("Shop island", JOBS, 3, "auto", 8, 5, []);
  });

  it("max agents and per group send their own values; a bad edit shows the error", async () => {
    vi.useFakeTimers();
    api.swarm_preview.mockResolvedValue({ ok: false, error: "per_group must be 2-10" });
    render(<SwarmBuilderCard payload={fixture} jobs={JOBS} />);
    fireEvent.change(screen.getByRole("slider", { name: "Max agents" }), { target: { value: "12" } });
    fireEvent.change(screen.getByRole("slider", { name: "Per group" }), { target: { value: "3" } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(SWARM_PREVIEW_DEBOUNCE_MS)));
    expect(api.swarm_preview).toHaveBeenCalledWith("Shop island", JOBS, 2, "auto", 12, 3, []);
    expect(screen.getByRole("alert").textContent).toBe("per_group must be 2-10");
  });
});

describe("SwarmBuilderCard editors and lane overlaps", () => {
  const seat = (name: string, paths: string[]) => ({
    name, job: `${name} job`, kind: "code", profile: "developer", model: "claude:claude-sonnet-5-5", paths,
    sub_plan: { title: `${name} job`, done: 0, total: 1, steps: [{ content: `${name} step` }] },
  });
  const draft3 = {
    ui: "swarm_builder", status: "needs_answers", goal: "Store",
    preview: {
      goal: "Store", detail: 2, agents: 3, max_agents: 8, per_group: 5,
      tree: [seat("Store lead", ["ui/index.html"]), seat("Plugin core", ["ui/**"]), seat("Plan lead", ["web/src/plan/**"])],
    },
  };

  it("two seats on one path: note shown, tree marks both red, Build off; fixing the lane turns it on and Build sends the edit", () => {
    api.swarm_preview.mockResolvedValue(undefined);
    const onBuild = vi.fn();
    const { container } = render(<SwarmBuilderCard payload={draft3} jobs={JOBS} onBuild={onBuild} />);
    const build = () => screen.getByRole("button", { name: "Build" }) as HTMLButtonElement;

    expect(build().disabled).toBe(true);
    expect(within(screen.getByLabelText("Lane overlaps")).getByText("Store lead ⚠ lane overlaps Plugin core: ui/index.html")).toBeTruthy();
    const red = [...container.querySelectorAll("li.swarm-tree-seat.swarm-tree-node--overlap")].map((r) => r.querySelector(".swarm-tree-seat-name")?.textContent);
    expect(red).toEqual(["Store lead", "Plugin core"]);
    // Each overlapping seat's editor shows its own note too.
    expect(within(container.querySelector('[data-seat="Plugin core"]') as HTMLElement).getByRole("alert").textContent).toBe(
      "Plugin core ⚠ lane overlaps Store lead: ui/index.html",
    );
    fireEvent.click(build());
    expect(onBuild).not.toHaveBeenCalled();

    const lane = within(container.querySelector('[data-seat="Plugin core"]') as HTMLElement).getByLabelText("Lane paths");
    fireEvent.change(lane, { target: { value: "plugin/**" } });
    fireEvent.blur(lane);

    expect(screen.queryByLabelText("Lane overlaps")).toBeNull();
    expect(container.querySelectorAll(".swarm-tree-node--overlap")).toHaveLength(0);
    expect(build().disabled).toBe(false);
    fireEvent.click(build());
    expect(onBuild).toHaveBeenCalledWith(expect.objectContaining({ edits: [{ seat: "Plugin core", paths: ["plugin/**"] }], confirm: true }));
  });

  it("an edit reruns swarm_preview with the card's edit list", async () => {
    vi.useFakeTimers();
    api.swarm_preview.mockResolvedValue(undefined);
    const { container } = render(<SwarmBuilderCard payload={draft3} jobs={JOBS} />);
    const lane = within(container.querySelector('[data-seat="Plan lead"]') as HTMLElement).getByLabelText("Lane paths");
    fireEvent.change(lane, { target: { value: "web/src/plan/rows/**" } });
    fireEvent.blur(lane);
    await act(async () => void (await vi.advanceTimersByTimeAsync(SWARM_PREVIEW_DEBOUNCE_MS)));
    expect(api.swarm_preview).toHaveBeenCalledWith("Store", JOBS, 2, "auto", 8, 5, [{ seat: "Plan lead", paths: ["web/src/plan/rows/**"] }]);
  });
});

describe("SwarmBuilderCard Build → status tree", () => {
  it("the confirm payload is the previewed answers", async () => {
    vi.useFakeTimers();
    api.swarm_preview.mockResolvedValue({ ok: true, ...fixture });
    const onBuild = vi.fn();
    render(<SwarmBuilderCard payload={fixture} jobs={JOBS} onBuild={onBuild} />);
    fireEvent.change(screen.getByRole("slider", { name: "Max agents" }), { target: { value: "10" } });
    await act(async () => void (await vi.advanceTimersByTimeAsync(SWARM_PREVIEW_DEBOUNCE_MS)));
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    const [goal, jobs, detail, agents, maxAgents, perGroup, edits] = api.swarm_preview.mock.calls[0];
    expect(onBuild).toHaveBeenCalledWith({
      goal, jobs, detail, agents, max_agents: maxAgents, per_group: perGroup, edits, confirm: true,
    });
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: "Build" })).toBeNull();
  });

  it("walks one seat through created → started → working → blocked → done", async () => {
    vi.useFakeTimers();
    render(<SwarmBuilderCard payload={fixture} jobs={JOBS} onBuild={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    const tester = () => screen.getByText(/^Tester · playtester/).closest("li")!;
    expect(tester().getAttribute("data-state")).toBe("waiting");
    expect(screen.getByText("Swarm: Shop island · 0/6 done")).toBeTruthy();

    emit({ type: "linked_agent", parent_conv_id: "lead", child_conv_id: "c-t", title: "Tester" });
    expect(tester().getAttribute("data-state")).toBe("created");
    emit({ type: "agent_started", conv_id: "c-t" });
    expect(tester().getAttribute("data-state")).toBe("started");
    emit({ type: "tool", conv_id: "c-t" });
    expect(tester().getAttribute("data-state")).toBe("working");
    emit({ type: "assistant_done", conv_id: "c-t", text: "BLOCKED: need the wallet API" });
    expect(tester().getAttribute("data-state")).toBe("blocked");
    expect(screen.getByText("Modeling lead · prop-artist · claude:claude-sonnet-5-5 · 2 steps").closest("li")!.getAttribute("data-state")).toBe("waiting");

    api.plan_progress.mockResolvedValue({ ok: true, progress: { "c-t": { done: 1, total: 1 } } });
    emit({ type: "plan_updated", conv_id: "lead" });
    await act(async () => void (await vi.advanceTimersByTimeAsync(300)));
    await act(async () => {});
    expect(api.plan_progress).toHaveBeenLastCalledWith(["c-t"]);
    expect(tester().getAttribute("data-state")).toBe("done");
    expect(tester().textContent).toContain("done 1/1");
    expect(screen.getByText("Swarm: Shop island · 1/6 done")).toBeTruthy();
  });

  it("nextSeatState: done is final; a plain stop keeps the state", () => {
    expect(nextSeatState("done", { type: "agent_started" })).toBe("done");
    expect(nextSeatState("working", { type: "agent_stopped", text: "finished" })).toBe("working");
    expect(nextSeatState("blocked", { type: "text_delta" })).toBe("working");
  });
});
