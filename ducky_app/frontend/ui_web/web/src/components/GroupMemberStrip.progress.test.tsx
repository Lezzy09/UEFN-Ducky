// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPlan, GroupMemberDto } from "../types/panel";
const api = vi.hoisted(() => ({ group_members: vi.fn(), get_plan: vi.fn(), get_settings: vi.fn(), set_muted: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../hooks/useAgentEventBus", () => ({ subscribeAgentEvents: () => () => undefined }));
import {
  GroupMemberStrip, laneCellLabel, laneModeOf, progressStep, progressText, subPlanProgress, sumProgress,
} from "./GroupMemberStrip";

const plan = (): ChatPlan => ({
  id: "team-plan", chat_id: "lead", title: "Faster tools", todos: [],
  nodes: [
    { id: "sp-search", content: "Search", status: "in_progress", kind: "subplan", children: [
      { id: "a", content: "git grep", status: "completed" },
      { id: "b", content: "Prune the walk", status: "in_progress" },
      { id: "c", content: "Loud truncation", status: "pending" },
      { id: "d", content: "Dropped idea", status: "cancelled" },
    ] },
    { id: "sp-rules", content: "Rules", status: "completed", kind: "subplan", children: [
      { id: "r1", content: "Enforce", status: "completed" },
      { id: "r2", content: "Move rules", status: "completed" },
    ] },
    { id: "sp-tools", content: "Rules in the tools", status: "in_progress", kind: "subplan", children: [
      { id: "t1", content: "One", status: "completed" },
      { id: "t2", content: "Two", status: "completed" },
      { id: "t3", content: "Three", status: "completed" },
      { id: "t4", content: "First line of uefn_* descriptions", status: "in_progress" },
      { id: "t5", content: "Five", status: "pending" },
    ] },
    { id: "sp-bar", content: "Team bar", status: "pending", kind: "subplan", children: [
      { id: "b1", content: "Rows show progress", status: "pending", after: ["t5"] } as never,
    ] },
  ],
});
const at = (node_id: string | null) => ({ plan_id: "team-plan", chat_id: "lead", node_id, title: "", status: "" });

const member = (name: string, node_id: string | null | "none", plan_id = "team-plan"): GroupMemberDto => ({
  name, profile_id: "", member_conv_id: name.toLowerCase(),
  observation: { group_id: "group", project_slug: "p", role: "member", runtime: "idle", observed_at: Date.now() / 1000,
    assignment: node_id === "none" ? null : { plan_id, chat_id: "lead", node_id, title: name, status: "in_progress" } },
});

afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });
const openTeam = () => fireEvent.click(screen.getByRole("button", { name: /^Team/ }));

describe("subPlanProgress", () => {
  it("counts the assigned sub plan's steps, leaves out cancelled ones and names the current step", () => {
    const p = subPlanProgress(plan(), { plan_id: "team-plan", chat_id: "lead", node_id: "sp-search", title: "", status: "" });
    expect(p).toEqual({ title: "Search", done: 1, total: 3, pct: 33, current: "Prune the walk" });
    expect(progressText(p!)).toBe("Search: 1/3 steps (33%) · now: Prune the walk");
    const done = subPlanProgress(plan(), { plan_id: "team-plan", chat_id: "lead", node_id: "sp-rules", title: "", status: "" });
    expect(done && progressText(done)).toBe("Rules: 2/2 steps (100%) · all done");
  });

  it("shows a member mid-plan as 3/5 · 60% with the step in progress", () => {
    const p = subPlanProgress(plan(), at("sp-tools"))!;
    expect([p.done, p.total, p.pct, progressStep(p)]).toEqual([3, 5, 60, "First line of uefn_* descriptions"]);
    expect(progressText(p)).toBe("Rules in the tools: 3/5 steps (60%) · now: First line of uefn_* descriptions");
    expect(progressStep(subPlanProgress(plan(), at("sp-rules"))!)).toBe("Done");
  });

  it("names the step a waiting part is blocked on (after)", () => {
    const p = subPlanProgress(plan(), at("sp-bar"))!;
    expect(p.waitingOn).toBe("Five");
    expect(progressStep(p)).toBe("Waiting on Five");
    expect(progressText(p)).toBe("Team bar: 0/1 steps (0%) · next: Rows show progress, waiting on Five");
  });

  it("a group sums its members' parts", () => {
    const sum = sumProgress([subPlanProgress(plan(), at("sp-tools"))!, subPlanProgress(plan(), at("sp-rules"))!], "Leads")!;
    expect([sum.done, sum.total, sum.pct, sum.current]).toEqual([5, 7, 71, "First line of uefn_* descriptions"]);
    expect(sumProgress([], "Empty")).toBeNull();
  });

  it("is unknown for another plan or a node that is gone", () => {
    expect(subPlanProgress(plan(), { plan_id: "old", chat_id: "lead", node_id: "sp-search", title: "", status: "" })).toBeNull();
    expect(subPlanProgress(plan(), { plan_id: "team-plan", chat_id: "lead", node_id: "gone", title: "", status: "" })).toBeNull();
    expect(subPlanProgress(null, { plan_id: "team-plan", chat_id: "lead", node_id: "sp-search", title: "", status: "" })).toBeNull();
  });

  it("covers the whole plan when the assignment names no node", () => {
    const whole = subPlanProgress(plan(), { plan_id: "team-plan", chat_id: "lead", node_id: null, title: "", status: "" });
    expect(whole).toMatchObject({ title: "Faster tools", done: 6, total: 11, pct: 55 });
  });
});

describe("team bar progress", () => {
  it("shows each agent's steps done, % and current step, and the team total", async () => {
    const rows = [member("Searcher", "sp-search"), member("Ruler", "sp-rules"), member("Helper", "sp-search"),
      member("Idle", "none")];
    api.group_members.mockResolvedValue({ ok: true, members: rows });
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    render(<GroupMemberStrip groupId="group" members={rows} onMembersChange={() => {}} onOpenMember={() => {}} />);
    // A sub plan shared by two agents counts once: 1/3 + 2/2.
    await screen.findByText("3/5 steps · 60%");
    expect(api.get_plan).toHaveBeenCalledWith("lead");
    expect(api.get_plan).toHaveBeenCalledTimes(1);
    openTeam();
    expect(screen.getByRole("columnheader", { name: "Sub plan" })).toBeTruthy();
    expect(screen.getAllByText("1/3")).toHaveLength(2);
    expect(screen.getAllByText("Prune the walk")).toHaveLength(2);
    expect(screen.getByText("2/2")).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();
    // The unassigned agent shows a dash, not a made-up count.
    expect(screen.getAllByTitle("No assigned sub plan seen")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Details for Searcher" }));
    expect(screen.getByText("Progress: Search: 1/3 steps (33%) · now: Prune the walk")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open Searcher" }).getAttribute("title")).toContain("now: Prune the walk");
  });

  it("a nested group row shows its rolled-up % and its agents n/m", async () => {
    const group: GroupMemberDto = { ...member("Verse", "sp-tools"), member_conv_id: "verse-group", is_group: true };
    const lead: GroupMemberDto = {
      ...member("Verse lead", "sp-search"),
      observation: { ...member("Verse lead", "sp-search").observation!, group_id: "verse-group" },
    };
    api.group_members.mockImplementation(async (id: string) =>
      ({ ok: true, members: id === "verse-group" ? [lead] : [group] }));
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    render(<GroupMemberStrip groupId="group" members={[group]} onMembersChange={() => {}} onOpenMember={() => {}} />);
    openTeam();
    // The group's own part (3/5) plus its agent's (1/3): 4/8.
    await screen.findByText("50%");
    expect(screen.getByText("Verse lead")).toBeTruthy();
    expect(screen.getByText("1/3")).toBeTruthy();
    expect(screen.getByText("Prune the walk")).toBeTruthy();
  });

  it("muting a nested group folds it to one row with its rollup; unmute brings its rows back", async () => {
    const group: GroupMemberDto = { ...member("Verse", "sp-tools"), member_conv_id: "verse-group", is_group: true };
    const lead: GroupMemberDto = {
      ...member("Verse lead", "sp-search"),
      observation: { ...member("Verse lead", "sp-search").observation!, group_id: "verse-group" },
    };
    api.group_members.mockImplementation(async (id: string) =>
      ({ ok: true, members: id === "verse-group" ? [lead] : [group] }));
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    api.set_muted.mockImplementation(async (id: string, muted: boolean) => ({ ok: true, id, muted }));
    render(<GroupMemberStrip groupId="group" members={[group]} onMembersChange={() => {}} onOpenMember={() => {}} />);
    openTeam();
    await screen.findByText("Verse lead");
    fireEvent.click(screen.getByRole("button", { name: "Mute Verse" }));
    await waitFor(() => expect(screen.queryByText("Verse lead")).toBeNull());
    expect(api.set_muted).toHaveBeenCalledWith("verse-group", true);
    expect(screen.getByText("MUTED")).toBeTruthy();
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /agents$/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Unmute Verse" }));
    await screen.findByText("Verse lead");
    expect(api.set_muted).toHaveBeenLastCalledWith("verse-group", false);
    expect(screen.queryByText("MUTED")).toBeNull();
  });

  it("a muted agent row is name and progress only, from the chat's muted flag", async () => {
    const rows = [member("Searcher", "sp-search")];
    api.group_members.mockResolvedValue({ ok: true, members: rows });
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    render(<GroupMemberStrip groupId="group" members={rows} allChats={[{ id: "searcher", name: "Searcher", muted: true }]}
      onMembersChange={() => {}} onOpenMember={() => {}} />);
    openTeam();
    await screen.findByText("1/3");
    expect(screen.getByText("MUTED")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open Searcher" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Details for Searcher" })).toBeNull();
    expect(screen.queryByTitle("Change Searcher's model")).toBeNull();
    expect(screen.getByRole("button", { name: "Unmute Searcher" })).toBeTruthy();
  });

  it("shows no progress for an assignment into a different plan", async () => {
    const rows = [member("Searcher", "sp-search", "an-old-plan")];
    api.group_members.mockResolvedValue({ ok: true, members: rows });
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    render(<GroupMemberStrip groupId="group" members={rows} onMembersChange={() => {}} onOpenMember={() => {}} />);
    await waitFor(() => expect(api.get_plan).toHaveBeenCalled());
    openTeam();
    expect(screen.queryByText(/steps ·/)).toBeNull();
    expect(screen.getByTitle("No assigned sub plan seen")).toBeTruthy();
  });

});

describe("lane column", () => {
  const laned = (): GroupMemberDto[] => [
    { ...member("Searcher", "sp-search"), write_allowed: ["src/showme/**", "a.ts", "b.ts"] },
    member("Free", "none"),
  ];
  const show = async (mode: string | undefined) => {
    api.group_members.mockResolvedValue({ ok: true, members: laned() });
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: {} });
    api.get_settings.mockResolvedValue(mode === undefined ? {} : { write_lanes_mode: mode });
    render(<GroupMemberStrip groupId="group" members={laned()} onMembersChange={() => {}} onOpenMember={() => {}} />);
    openTeam();
    return screen.findByTitle(/^Lane:/);
  };

  it("shows 'Blocks' when lanes are enforced, with every glob and the meaning on hover", async () => {
    const button = await show("enforce");
    await waitFor(() => expect(button.textContent).toBe("src/showme/ +2Blocks"));
    expect(button.getAttribute("title")).toBe(
      "Lane:\nsrc/showme/**\na.ts\nb.ts\nBlocks: Ducky's file tools refuse a write outside the lane, and the agent is " +
      "told to stay inside it. Commands run in native shells are not checked.");
    fireEvent.click(button);
    expect(screen.getByText(/A lane is the set of files Searcher may write/).textContent).toContain(
      "Only the group lead or you can change a lane.");
    expect(screen.queryByText(/coverage is unknown/)).toBeNull();
  });

  it("shows 'Warns only' when lanes only flag writes", async () => {
    const button = await show("shadow");
    await waitFor(() => expect(button.textContent).toContain("Warns only"));
    expect(button.getAttribute("title")).toContain("Warns only: a write outside the lane still goes through");
  });

  it("an agent without a lane reads 'Any file' and gets no mode badge", async () => {
    await show("enforce");
    const free = screen.getByTitle("No write lane: this agent may write any file.");
    expect(free.textContent).toBe("Any file");
    expect(laneCellLabel(null)).toBe("Any file");
  });

  it("falls back to the default, Blocks, and says so when the app reports no lane mode", async () => {
    const button = await show(undefined);
    expect(button.textContent).toContain("Blocks");
    await waitFor(() => expect(api.get_settings).toHaveBeenCalled());
    expect(button.getAttribute("title")).toContain("did not report its lane setting; Blocks is the default");
    expect(laneModeOf({ write_lanes_mode: "SHADOW" })).toEqual({ mode: "shadow", reported: true });
    expect(laneModeOf({ write_lanes_mode: "bogus" })).toEqual({ mode: "enforce", reported: false });
  });
});
