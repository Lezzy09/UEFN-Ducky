import { describe, expect, it } from "vitest";
import type { AgentProfileDto, ChatPlan, GroupMemberDto, PlanNode } from "../../types/panel";
import { buildRoster, memberDisplayName, rollupProgress, type RosterNode } from "./teamRoster";

/** A section of `total` steps, the first `done` of them completed. */
const section = (id: string, content: string, done: number, total: number): PlanNode => ({
  id,
  content,
  status: done === total ? "completed" : "in_progress",
  kind: "subplan",
  children: Array.from({ length: total }, (_, i) => ({
    id: `${id}-${i}`,
    content: `${content} step ${i + 1}`,
    status: i < done ? "completed" : i === done ? "in_progress" : "pending",
  })),
});

const plan = (): ChatPlan => ({
  id: "team-plan",
  chat_id: "lead",
  title: "Shop island",
  todos: [],
  nodes: [
    section("sp-art", "Art: assets", 3, 10),
    section("sp-code", "Code: gameplay", 3, 5),
    section("sp-verse", "Verse: combat", 3, 5),
    section("sp-narr", "Narrative", 2, 4),
    section("sp-test", "Tests", 2, 3),
    section("sp-lead", "Wrap up", 2, 2),
  ],
});

const seat = (id: string, name: string, hub: string, node_id: string | null, extra: Partial<GroupMemberDto> = {}): GroupMemberDto => ({
  member_conv_id: id,
  profile_id: "",
  name,
  ...extra,
  observation: {
    observed_at: 0,
    runtime: "idle",
    group_id: hub,
    project_slug: null,
    role: "member",
    assignment: node_id ? { plan_id: "team-plan", chat_id: "lead", node_id, title: name, status: "in_progress" } : null,
  },
});

const verseCoder = { id: "verse-coder", name: "Verse Coder" } as AgentProfileDto;

/** Lead · Art: assets · Code: gameplay (Verse lead) · Narrative lead · Tester. */
const tree = (codeRoster: GroupMemberDto[] = [seat("verse", "Verse lead", "code", "sp-verse")]): RosterNode[] =>
  buildRoster({
    groupId: "root",
    leaderConvId: "lead",
    members: [
      seat("lead", "Lead", "root", null),
      seat("art", "Art: assets", "root", "sp-art", { is_group: true }),
      seat("code", "Code: gameplay", "root", "sp-code", { is_group: true }),
      seat("narr", "Narrative lead", "root", "sp-narr"),
      seat("test", "Tester", "root", "sp-test"),
    ],
    rosters: { code: codeRoster },
    folders: [],
    allChats: [],
    profileById: new Map([["verse-coder", verseCoder]]),
    labelFor: () => "Ducky",
  });

const byName = (nodes: RosterNode[], name: string): RosterNode => {
  for (const n of nodes) {
    if (n.name === name) return n;
    const inside = n.children.length ? byName(n.children, name) : undefined;
    if (inside) return inside;
  }
  return undefined as never;
};

describe("rollupProgress", () => {
  const plans = { lead: plan() };

  it("rolls the target tree up: Lead 52%, Code 60%, Verse lead 3/5", () => {
    const nodes = tree();
    expect(rollupProgress(byName(nodes, "Lead"), plans)).toMatchObject({ done: 15, total: 29, pct: 52 });
    expect(rollupProgress(byName(nodes, "Code: gameplay"), plans)).toMatchObject({ done: 6, total: 10, pct: 60 });
    expect(rollupProgress(byName(nodes, "Verse lead"), plans)).toMatchObject({ done: 3, total: 5, pct: 60 });
    expect(rollupProgress(byName(nodes, "Art: assets"), plans)).toMatchObject({ done: 3, total: 10, pct: 30 });
    expect(rollupProgress(byName(nodes, "Narrative lead"), plans)).toMatchObject({ done: 2, total: 4 });
    expect(rollupProgress(byName(nodes, "Tester"), plans)).toMatchObject({ done: 2, total: 3 });
  });

  it("counts a sub plan shared by two rows once", () => {
    const nodes = tree([seat("verse", "Verse lead", "code", "sp-verse"), seat("verse2", "Verse coder 2", "code", "sp-verse")]);
    expect(rollupProgress(byName(nodes, "Code: gameplay"), plans)).toMatchObject({ done: 6, total: 10, pct: 60 });
  });

  it("counts a step once when a row's sub plan sits inside its group's", () => {
    const nested = plan();
    const code = nested.nodes!.find((n) => n.id === "sp-code")!;
    const verse = nested.nodes!.find((n) => n.id === "sp-verse")!;
    code.children = [...code.children!, verse];
    nested.nodes = nested.nodes!.filter((n) => n !== verse);
    expect(rollupProgress(byName(tree(), "Code: gameplay"), { lead: nested })).toMatchObject({ done: 6, total: 10 });
  });

  it("is null for a group with nothing assigned, and ignores another group's observation", () => {
    const nodes = tree([seat("verse", "Verse lead", "elsewhere", "sp-verse")]);
    expect(rollupProgress(byName(nodes, "Verse lead"), plans)).toBeNull();
    expect(rollupProgress(byName(nodes, "Code: gameplay"), plans)).toMatchObject({ done: 3, total: 5 });
    expect(rollupProgress(byName(nodes, "Art: assets"), {})).toBeNull();
  });

  it("reads assignments through the given observation lookup", () => {
    const nodes = tree();
    const none = rollupProgress(byName(nodes, "Code: gameplay"), plans, () => undefined);
    expect(none).toBeNull();
  });
});

describe("seat names", () => {
  it("shows the seat name, with the profile and model in the hover", () => {
    const m: GroupMemberDto = { member_conv_id: "s", profile_id: "verse-coder", name: "Search lead", model: "codex:gpt-5" };
    expect(memberDisplayName(m, verseCoder, () => "Ducky")).toBe("Search lead");
    const [row] = buildRoster({
      groupId: "g", leaderConvId: "", members: [m], rosters: {}, folders: [], allChats: [],
      profileById: new Map([["verse-coder", verseCoder]]), labelFor: () => "Ducky",
    });
    expect(row.name).toBe("Search lead");
    expect(row.hover).toMatch(/^Verse Coder · .*gpt-5/i);
  });

  it("falls back to the duck name, then the profile, then the style label", () => {
    const base: GroupMemberDto = { member_conv_id: "s", profile_id: "verse-coder", name: "" };
    expect(memberDisplayName({ ...base, ducky_name: "Hacker" }, verseCoder, () => "Ducky")).toBe("Hacker");
    expect(memberDisplayName(base, verseCoder, () => "Ducky")).toBe("Verse Coder");
    expect(memberDisplayName(base, undefined, () => "Ducky")).toBe("Ducky");
  });
});
