import { describe, expect, it } from "vitest";
import { planGroupExtraction } from "./extractGroup";
import type { AutomationGraphDto } from "../types/panel";

const isStarter = (node: { type: string }) => node.type.startsWith("start.");
const n = (id: string, type = "flow.wait", x = 0, y = 0) => ({ id, type, x, y, config: {} });
const e = (source: string, target: string, kind = "main") => ({ source, target, kind });

// start → check(branch) → [a → b] → done ; the group holds a and b.
const base: AutomationGraphDto = {
  nodes: [n("start", "start.manual"), n("check", "flow.branch", 200), n("a", "flow.wait", 400, 40), n("b", "flow.wait", 680, 40), n("done", "flow.wait", 960)],
  edges: [e("start", "check"), e("check", "a", "true"), e("a", "b"), e("b", "done")],
  groups: [{ id: "g", name: "Steps", node_ids: ["a", "b"] }],
};

describe("group to reusable workflow", () => {
  it("moves the group's nodes behind Inputs and Return, and runs it from the same place", () => {
    const plan = planGroupExtraction(base, "g", isStarter);
    if (!plan.ok) throw new Error(plan.error);
    expect(plan.child.nodes.map((node) => [node.id, node.type, node.x, node.y])).toEqual([
      ["inputs", "flow.input", 0, 0], ["a", "flow.wait", 280, 0], ["b", "flow.wait", 560, 0], ["return", "flow.output", 920, 0],
    ]);
    expect(plan.child.edges).toEqual([e("inputs", "a"), e("a", "b"), e("b", "return")]);
    const parent = plan.parent("wf-new", "call", "Steps");
    expect(parent.nodes.map((node) => node.id)).toEqual(["start", "check", "done", "call"]);
    expect(parent.nodes[3]).toEqual({ id: "call", type: "workflow.call", x: 400, y: 40, label: "Steps", description: "", config: { workflow_id: "wf-new", args: {}, share: true } });
    // The Branch's True wire now reaches the call; the call continues where the group did.
    expect(parent.edges).toEqual([e("start", "check"), e("check", "call", "true"), e("call", "done")]);
    expect(parent.groups).toEqual([]);
  });

  it("keeps nested boxes, drops the moved group, and lands the call in the box around it", () => {
    const graph: AutomationGraphDto = { ...base, nodes: [...base.nodes, n("c", "flow.wait", 400, 200)], edges: [...base.edges, e("a", "c")], groups: [
      { id: "outer", name: "Outer", node_ids: ["check"] },
      { id: "g", name: "Steps", node_ids: ["b"], parent_id: "outer" },
      { id: "inner", name: "Inner", node_ids: ["a", "c"], parent_id: "g" },
    ] };
    const plan = planGroupExtraction(graph, "g", isStarter);
    if (!plan.ok) throw new Error(plan.error);
    expect(plan.child.groups).toEqual([{ id: "inner", name: "Inner", node_ids: ["a", "c"] }]);
    expect(plan.parent("wf", "call", "Steps").groups).toEqual([{ id: "outer", name: "Outer", node_ids: ["check", "call"] }]);
  });

  it("carries the kind of a wire that leaves the group onto its Return", () => {
    const graph: AutomationGraphDto = {
      nodes: [n("s", "start.manual"), n("q", "flow.branch", 200), n("end", "flow.end", 400), n("next", "flow.wait", 600)],
      edges: [e("s", "q"), e("q", "next", "true"), e("q", "end", "false")],
      groups: [{ id: "g", name: "Ask", node_ids: ["q", "end"] }],
    };
    const plan = planGroupExtraction(graph, "g", isStarter);
    if (!plan.ok) throw new Error(plan.error);
    expect(plan.child.edges).toContainEqual(e("q", "return", "true"));
    expect(plan.parent("wf", "call", "Ask").edges).toEqual([e("s", "call"), e("call", "next")]);
  });

  it("refuses what one node can't stand in for", () => {
    const refuse = (graph: AutomationGraphDto) => { const plan = planGroupExtraction(graph, "g", isStarter); return plan.ok ? "" : plan.error; };
    expect(refuse({ ...base, groups: [{ id: "g", name: "S", node_ids: ["start", "check"] }] })).toContain("Starts");
    expect(refuse({ ...base, edges: [...base.edges, e("a", "start")] })).toContain("different next steps");
    expect(refuse({ ...base, nodes: [...base.nodes, n("loop", "flow.foreach")], edges: [...base.edges, e("loop", "done", "each")], groups: [{ id: "g", name: "S", node_ids: ["loop"] }] })).toContain("For each");
    expect(refuse({ ...base, groups: [] })).toContain("no longer exists");
  });

  it("starts the new workflow at nodes nothing led to before", () => {
    const graph: AutomationGraphDto = { nodes: [n("a"), n("b", "flow.wait", 300)], edges: [e("a", "b")], groups: [{ id: "g", name: "All", node_ids: ["a", "b"] }] };
    const plan = planGroupExtraction(graph, "g", isStarter);
    if (!plan.ok) throw new Error(plan.error);
    expect(plan.child.edges).toEqual([e("inputs", "a"), e("a", "b")]);  // no way out: no Return
    expect(plan.child.nodes.some((node) => node.type === "flow.output")).toBe(false);
    expect(plan.parent("wf", "call", "All").edges).toEqual([]);  // the call is a start, as a was
  });
});
