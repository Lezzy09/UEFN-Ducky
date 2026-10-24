// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SWARM_BUILD_PROMPT,
  SWARM_CARD_EVENT,
  SWARM_CHANGE_PROMPT,
  SWARM_DETAIL_DEBOUNCE_MS,
  SWARM_REVEAL_MS,
  SwarmCard,
  parseSwarmResult,
  swarmDetailPrompt,
  swarmRollup,
  useSwarmCardSend,
} from "./SwarmCard";
import { resolveToolPresenterBlocks, resolveToolPresenterView } from "./resolveToolPresenter";

const preview = JSON.stringify({
  ok: true,
  status: "needs_confirm",
  goal: "Shop island",
  preview: {
    agents: 6,
    tree: [
      {
        group: "Code: gameplay",
        purpose: "gameplay",
        seats: [
          { name: "Verse lead", profile: "verse-coder", model: "claude-opus-5-5" },
          { name: "UI lead", profile: "ui-engineer", model: "claude-sonnet-5-5" },
        ],
      },
      { name: "Narrative lead", profile: "developer", model: "claude-sonnet-5-5" },
      {
        group: "Art: assets",
        muted: true,
        seats: [
          { name: "Modeling lead", profile: "3d-modeler", model: "codex:gpt-5-mini" },
          { name: "Texture lead", profile: "material-artist", model: "codex:gpt-5-mini" },
        ],
      },
      { name: "Tester", profile: "tester", model: "codex:gpt-5-mini" },
    ],
  },
});

function building(testerCreated: boolean) {
  return JSON.stringify({
    status: "building",
    goal: "Shop island",
    agents: 3,
    tree: [
      {
        group: "Verse: combat",
        group_id: "g1",
        seats: [
          { name: "Verse lead", conv_id: "c1" },
          { name: "Verse coder 2", conv_id: "c2" },
        ],
      },
      { name: "Tester", created: testerCreated },
    ],
  });
}

const done = JSON.stringify({
  status: "done",
  goal: "Shop island",
  agents: 3,
  tree: [
    {
      group: "Verse: combat",
      group_id: "g1",
      sub_plan: { title: "Verse: combat", done: 3, total: 5 },
      seats: [
        { name: "Verse lead", conv_id: "c1", sub_plan: "Verse: combat 3/5" },
        { name: "Verse coder 2", conv_id: "c2" },
      ],
    },
    { name: "Tester", conv_id: "c3", sub_plan: { title: "Tests", done: 0, total: 2 } },
  ],
});

function nodeByText(text: string | RegExp): Element {
  const label = screen.getByText(text);
  const g = label.closest("g");
  if (!g) throw new Error("no node group");
  return g;
}

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("reduce"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SwarmCard preview", () => {
  it("draws the 6-agent tree with roles, models and the muted group", () => {
    const onSend = vi.fn();
    render(<SwarmCard resultText={preview} onSend={onSend} />);

    expect(screen.getByText("Swarm preview: Shop island · 6 agents · 3 groups")).toBeTruthy();
    expect(screen.getByText("Lead · Shop island")).toBeTruthy();
    expect(screen.getByText("Code: gameplay · 2 agents")).toBeTruthy();
    expect(screen.getByText("Verse lead · verse-coder · claude-opus-5-5")).toBeTruthy();
    expect(screen.getByText("UI lead · ui-engineer · claude-sonnet-5-5")).toBeTruthy();
    expect(screen.getByText("Narrative lead · developer · claude-sonnet-5-5")).toBeTruthy();
    expect(screen.getByText("Tester · tester · codex:gpt-5-mini")).toBeTruthy();

    // Muted group: one amber row, its seats not drawn.
    const art = nodeByText("Art: assets · 2 agents · MUTED");
    expect(art.getAttribute("class")).toContain("rich-c-amber");
    expect(screen.queryByText(/Modeling lead/)).toBeNull();

    expect(screen.getByText(/6 agents · 3 groups · models: claude-sonnet-5-5 ×2, codex:gpt-5-mini ×3, claude-opus-5-5$/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(onSend).toHaveBeenNthCalledWith(1, "build", SWARM_BUILD_PROMPT);
    expect(onSend).toHaveBeenNthCalledWith(2, "change", SWARM_CHANGE_PROMPT);
    expect(SWARM_BUILD_PROMPT).toContain("confirm=true");
  });

  it("is registered for ducky_swarm_create, prefixed or not, only for card statuses", () => {
    expect(resolveToolPresenterView("ducky_swarm_create", preview)).toBe(SwarmCard);
    expect(resolveToolPresenterView("mcp__uefn__ducky_swarm_create", preview)).toBe(SwarmCard);
    expect(resolveToolPresenterView("ducky_swarm_create", JSON.stringify({ status: "needs_answers" }))).toBeNull();
    expect(resolveToolPresenterView("find_devices", preview)).toBeNull();
    const blocks = resolveToolPresenterBlocks({ toolName: "ducky_swarm_create", arguments: {}, resultText: preview, isSuccess: true });
    expect(blocks?.[0]).toMatchObject({ type: "code", language: "chart" });
  });
});

describe("SwarmCard detail slider", () => {
  const withLevels = (() => {
    const r = JSON.parse(preview);
    r.preview.detail = 2;
    r.preview.levels = [
      { detail: 1, agents: 3 },
      { detail: 2, agents: 6 },
      { detail: 3, agents: 7 },
      { detail: 4, agents: 9 },
    ];
    return JSON.stringify(r);
  })();

  it("shows 4 stops with agent counts, starts at preview.detail, sends detail once, then builds that level", () => {
    vi.useFakeTimers();
    const onSend = vi.fn();
    render(<SwarmCard resultText={withLevels} onSend={onSend} />);

    const slider = screen.getByRole("slider", { name: "Detail" }) as HTMLInputElement;
    expect(slider.value).toBe("2");
    for (const stop of ["Areas · 3 agents", "Jobs · 6 agents", "Parts · 7 agents", "Parts in sub-groups · 9 agents"]) {
      expect(screen.getByText(stop)).toBeTruthy();
    }

    fireEvent.change(slider, { target: { value: "3" } });
    expect(onSend).not.toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(SWARM_DETAIL_DEBOUNCE_MS));
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("detail", swarmDetailPrompt(3));
    expect(swarmDetailPrompt(3)).toContain("detail=3");
    expect(swarmDetailPrompt(3)).not.toContain("confirm=true");
    expect(slider.value).toBe("3");

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(onSend).toHaveBeenLastCalledWith("build", expect.stringMatching(/detail=3 and confirm=true/));
  });

  it("no levels → no slider", () => {
    render(<SwarmCard resultText={preview} />);
    expect(screen.queryByRole("slider")).toBeNull();
  });
});

describe("SwarmCard sends through its own chat pane", () => {
  function Pane({ send, children }: { send: (text: string) => void; children?: ReactNode }) {
    const [host, setHost] = useState<HTMLDivElement | null>(null);
    useSwarmCardSend(host, send);
    return <div ref={setHost}>{children}</div>;
  }

  it("Build bubbles one event to the pane showing the card; another pane sends nothing", () => {
    const mine = vi.fn();
    const other = vi.fn();
    const onWindow = vi.fn();
    window.addEventListener(SWARM_CARD_EVENT, onWindow);
    render(
      <>
        <Pane send={mine}>
          <SwarmCard resultText={preview} />
        </Pane>
        <Pane send={other} />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    window.removeEventListener(SWARM_CARD_EVENT, onWindow);
    expect(mine).toHaveBeenCalledTimes(1);
    expect(mine).toHaveBeenCalledWith(SWARM_BUILD_PROMPT);
    expect(other).not.toHaveBeenCalled();
    expect(onWindow).not.toHaveBeenCalled();
  });
});

describe("SwarmCard build animation", () => {
  it("reveals nodes in creation order, then shows live progress when done", () => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    const { rerender } = render(<SwarmCard resultText={building(false)} />);

    const group = nodeByText("Verse: combat · 2 agents");
    const lead = nodeByText("Verse lead");
    const coder = nodeByText("Verse coder 2");
    const tester = nodeByText("Tester");
    expect(group.classList.contains("swarm-node--pending")).toBe(true);
    expect(lead.classList.contains("swarm-node--created")).toBe(false);

    act(() => void vi.advanceTimersByTime(SWARM_REVEAL_MS));
    expect(group.classList.contains("swarm-node--created")).toBe(true);
    expect(group.classList.contains("swarm-node--animate")).toBe(true);
    expect(lead.classList.contains("swarm-node--created")).toBe(false);

    act(() => void vi.advanceTimersByTime(SWARM_REVEAL_MS));
    act(() => void vi.advanceTimersByTime(SWARM_REVEAL_MS));
    expect(lead.getAttribute("data-swarm-step")).toBe("1");
    expect(coder.getAttribute("data-swarm-step")).toBe("2");
    expect(tester.classList.contains("swarm-node--pending")).toBe(true);
    expect(screen.getByText("Building 2/3 agents…")).toBeTruthy();
    expect(document.querySelectorAll("path.swarm-edge--created").length).toBe(3);

    rerender(<SwarmCard resultText={done} />);
    act(() => void vi.advanceTimersByTime(SWARM_REVEAL_MS));
    expect(nodeByText("Tester · 0/2").classList.contains("swarm-node--created")).toBe(true);
    expect(nodeByText("Verse lead · 3/5").getAttribute("data-swarm-step")).toBe("1");
    expect(screen.getByText("Verse: combat · 60%")).toBeTruthy();
    expect(screen.getByText("Lead · 43%")).toBeTruthy();
    expect(screen.getByText("Built 3 agents · 3/7 steps")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Build" })).toBeNull();
  });

  it("leaves no timer running after unmount", () => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    const { unmount } = render(<SwarmCard resultText={building(true)} />);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows created nodes at once, without animation, under reduced motion", () => {
    vi.useFakeTimers();
    stubReducedMotion(true);
    render(<SwarmCard resultText={building(false)} />);
    expect(vi.getTimerCount()).toBe(0);
    const lead = nodeByText("Verse lead");
    expect(lead.classList.contains("swarm-node--created")).toBe(true);
    expect(document.querySelectorAll(".swarm-node--animate, .swarm-edge--animate").length).toBe(0);
    expect(nodeByText("Tester").classList.contains("swarm-node--pending")).toBe(true);
  });

  it("a finished card seen first (history) shows everything without animating", () => {
    vi.useFakeTimers();
    stubReducedMotion(false);
    render(<SwarmCard resultText={done} />);
    expect(vi.getTimerCount()).toBe(0);
    expect(nodeByText("Tester · 0/2").classList.contains("swarm-node--created")).toBe(true);
    expect(document.querySelectorAll(".swarm-node--animate").length).toBe(0);
  });
});

describe("swarm rollup", () => {
  it("counts a sub plan shared by a group and its seat once", () => {
    const data = parseSwarmResult(done);
    expect(data).not.toBeNull();
    expect(swarmRollup(data!.groups[0])).toEqual({ done: 3, total: 5, pct: 60 });
    expect(swarmRollup(data!)).toEqual({ done: 3, total: 7, pct: 43 });
  });
});
