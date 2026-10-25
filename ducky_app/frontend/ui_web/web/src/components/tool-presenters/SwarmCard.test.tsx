// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SWARM_BUILD_PROMPT,
  SWARM_CARD_EVENT,
  SWARM_CHANGE_PROMPT,
  SWARM_DETAIL_DEBOUNCE_MS,
  SWARM_PLAN_CHANGE_PROMPT,
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
    expect(document.querySelector("svg")?.textContent).not.toContain("Modeling lead");

    expect(screen.getByText(/^6 agents · 0 steps · models: claude-sonnet-5-5 ×2, codex:gpt-5-mini ×3, claude-opus-5-5$/)).toBeTruthy();

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

describe("SwarmCard plan", () => {
  const withPlan = JSON.stringify({
    status: "needs_confirm",
    goal: "Shop island",
    preview: {
      agents: 4,
      tree: [
        {
          group: "Code: gameplay",
          muted: false,
          seats: [
            { name: "Verse lead", sub_plan: { title: "Verse: combat", total: 3, steps: ["Damage system", { content: "Spawner wiring" }, "Tests"] } },
            { name: "UI lead", sub_plan: { title: "UI: HUD", total: 4 } },
          ],
        },
        {
          group: "Art: assets",
          muted: true,
          seats: [{ name: "Modeling lead", sub_plan: { title: "Modeling: props", total: 2 } }],
        },
        { name: "Tester", sub_plan: { title: "Tests", total: 1 } },
      ],
      plan: { sections: [{ title: "Modeling: props", steps: [{ content: "Blockout" }, { content: "Hero props" }] }] },
    },
  });

  it("lists each seat's steps under its group, collapses muted groups, and totals the steps", () => {
    render(<SwarmCard resultText={withPlan} />);
    expect(screen.getByText("Verse lead:").parentElement?.textContent).toBe("Verse lead: Damage system · Spawner wiring · Tests");
    expect(screen.getByText("UI lead:").parentElement?.textContent).toBe("UI lead: 4 steps");
    expect(screen.getByText("Modeling lead:").parentElement?.textContent).toBe("Modeling lead: Blockout · Hero props");
    expect(screen.getByText("Tester:").parentElement?.textContent).toBe("Tester: 1 step");

    const code = screen.getByText("Code: gameplay (2 agents · 7 steps)").closest("details") as HTMLDetailsElement;
    const art = screen.getByText("Art: assets (1 agent · 2 steps) · MUTED").closest("details") as HTMLDetailsElement;
    expect(code.open).toBe(true);
    expect(art.open).toBe(false);
    fireEvent.click(art.querySelector("summary")!);
    expect(art.open).toBe(true);
    fireEvent.click(code.querySelector("summary")!);
    expect(code.open).toBe(false);

    expect(screen.getByText(/^4 agents · 10 steps/)).toBeTruthy();
  });

  it("is only on the preview", () => {
    render(<SwarmCard resultText={done} />);
    expect(screen.queryByLabelText("Plan")).toBeNull();
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

describe("SwarmCard from a plan", () => {
  const fromPlan = (conflicts: unknown[]) =>
    JSON.stringify({
      status: "needs_confirm",
      goal: "Swarm speed",
      plan_id: "7df73ab45675",
      conflicts,
      preview: {
        agents: 2,
        tree: [
          { name: "U1 Card shell", sub_plan: { title: "U1 Card shell", total: 2 } },
          { name: "U2 Tree", sub_plan: { title: "U2 Tree", total: 1 } },
        ],
        plan: {
          title: "Swarm speed: no lag",
          sections: [
            { n: "7.4.1", title: "U1 Card shell", steps: [{ n: "7.4.1.1", content: "Builder card" }, { n: "7.4.1.2", content: "Sliders" }] },
            { n: "7.4.2", title: "U2 Tree", steps: [{ n: "7.4.2.1", content: "Live tree" }] },
          ],
        },
      },
    });

  it("titles the real plan, lists outline numbers, and Change edits the plan", () => {
    const onSend = vi.fn();
    render(<SwarmCard resultText={fromPlan([])} onSend={onSend} />);
    expect(screen.getByText("Swarm from plan: Swarm speed: no lag · 2 agents · 1 groups")).toBeTruthy();
    expect(screen.getByText("7.4.1 U1 Card shell")).toBeTruthy();
    expect(screen.getByText("7.4.1.2 Sliders")).toBeTruthy();
    expect(screen.getByText("7.4.2.1 Live tree")).toBeTruthy();
    expect(screen.queryByLabelText("Conflicts")).toBeNull();
    const build = screen.getByRole("button", { name: "Build" }) as HTMLButtonElement;
    expect(build.disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(onSend).toHaveBeenCalledWith("change", SWARM_PLAN_CHANGE_PROMPT);
    expect(SWARM_PLAN_CHANGE_PROMPT).toContain("edit the plan");
  });

  it("lists lane conflicts in red and disables Build while any exist", () => {
    const onSend = vi.fn();
    render(
      <SwarmCard
        resultText={fromPlan([{ path: "web/src/swarm/SwarmTree.tsx", seats: ["U1 Card shell", "U2 Tree"] }, "lanes.ts has two owners"])}
        onSend={onSend}
      />,
    );
    const list = screen.getByLabelText("Conflicts");
    expect(list.textContent).toContain("web/src/swarm/SwarmTree.tsx: U1 Card shell, U2 Tree");
    expect(list.textContent).toContain("lanes.ts has two owners");
    const build = screen.getByRole("button", { name: "Build" }) as HTMLButtonElement;
    expect(build.disabled).toBe(true);
    fireEvent.click(build);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("a jobs swarm (no plan_id) renders as before", () => {
    const data = parseSwarmResult(preview);
    expect(data?.planId).toBeUndefined();
    expect(data?.conflicts).toEqual([]);
    render(<SwarmCard resultText={preview} />);
    expect(screen.getByText("Swarm preview: Shop island · 6 agents · 3 groups")).toBeTruthy();
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
