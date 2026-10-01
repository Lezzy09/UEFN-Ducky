import { describe, expect, it } from "vitest";
import type { AutomationGraphDto, AutomationNodeDto } from "../types/panel";
import { aiTourSteps, buildWorkflowTour, withOpenStep } from "./workflowTour";

const byType = new Map<string, AutomationNodeDto>([
  ["start.manual", { type: "start.manual", label: "Manual", group: "Starting" }],
  ["input.text", { type: "input.text", label: "Input Text", group: "Inputs", exec: false, outputs: [{ id: "text", label: "Text", type: "text" }] }],
  ["logic.if", { type: "logic.if", label: "If", group: "Logic", description: "Checks a condition.", outputs: [{ id: "result", label: "Result", type: "boolean" }] }],
  ["flow.wait", { type: "flow.wait", label: "Wait", group: "Logic" }],
  ["util.preview", { type: "util.preview", label: "Preview", group: "Utility", exec: false, inputs: [{ id: "value", label: "Value", type: "any" }] }],
]);

const graph: AutomationGraphDto = {
  nodes: [
    { id: "s", type: "start.manual", x: 0, y: 0, config: {} },
    { id: "v", type: "input.text", x: 0, y: 0, config: {}, label: "Score" },
    { id: "i", type: "logic.if", x: 0, y: 0, config: { names: ["value"] }, label: "Passed?" },
    { id: "yes", type: "flow.wait", x: 0, y: 0, config: {}, label: "Celebrate" },
    { id: "no", type: "flow.wait", x: 0, y: 0, config: {}, label: "Try again" },
    { id: "t", type: "input.text", x: 0, y: 0, config: {}, label: "Caption" },
    { id: "p", type: "util.preview", x: 0, y: 0, config: {}, label: "Show it" },
  ],
  edges: [
    { source: "s", target: "i", kind: "main" },
    { source: "i", target: "yes", kind: "true" },
    { source: "i", target: "no", kind: "false" },
    { source: "v", target: "i", kind: "data", source_pin: "text", target_pin: "value" },
    { source: "t", target: "p", kind: "data", source_pin: "text", target_pin: "value" },
  ],
};

describe("Tour this workflow", () => {
  it("walks the steps in run order, with what feeds them, routes, and the ends last", () => {
    const steps = buildWorkflowTour(graph, byType);
    expect(steps.map((step) => step.target)).toEqual([
      "workflows.node.s", "workflows.node.i", "workflows.node.yes", "workflows.node.no", "workflows.node.t", "workflows.node.p",
    ]);
    const check = steps[1];
    expect(check.title).toBe("Passed?");
    expect(check.body).toContain("Checks a condition.");
    expect(check.body).toContain("**Worked out first:** Score");
    expect(check.body).toContain("**Then:** True → Celebrate, False → Try again");
    expect(steps[4].body).toContain("**Then:** Show it");  // a pipeline is walked node by node
    expect(steps[5].body).toContain("**Runs on its own**");
  });

  it("walks a pipeline of value nodes from its first input to its end", () => {
    const pipe: AutomationGraphDto = {
      nodes: [
        { id: "p", type: "util.preview", x: 0, y: 0, config: {}, label: "End" },
        { id: "b", type: "input.text", x: 0, y: 0, config: {}, label: "Middle" },
        { id: "a", type: "input.text", x: 0, y: 0, config: {}, label: "Start" },
      ],
      edges: [
        { source: "a", target: "b", kind: "data", source_pin: "text", target_pin: "value" },
        { source: "b", target: "p", kind: "data", source_pin: "text", target_pin: "value" },
      ],
    };
    expect(buildWorkflowTour(pipe, byType).map((step) => step.title)).toEqual(["Start", "Middle", "End"]);
  });

  it("maps the AI's steps and opens the workflow on the first one", () => {
    const steps = aiTourSteps([
      { node_ids: ["i", "yes"], title: "The check", body: "…" },
      { group_id: "g1", title: "Loop" },
      { target: "workflows.toolbar.run", title: "Test" },
      { title: "nothing to point at" },
    ]);
    expect(steps).toEqual([
      { target: "workflows.node.i", title: "The check", body: "…", action: { id: "workflows.select", args: { node_ids: ["i", "yes"] } } },
      { target: "workflows.group.g1", title: "Loop", body: "", action: { id: "workflows.select", args: { group_id: "g1" } } },
      { target: "workflows.toolbar.run", title: "Test", body: "" },
    ]);
    const opened = withOpenStep(steps, "wf1");
    expect(opened[0]).toMatchObject({ navigate: "workflows", action: { id: "workflows.select", args: { node_ids: ["i", "yes"], id: "wf1" } } });
    expect(withOpenStep([{ target: "workflows.node.s", title: "Start" }], "wf1")[0].action).toEqual({ id: "workflows.open", args: { id: "wf1" } });
    expect(withOpenStep([], "wf1")).toEqual([]);
  });
});
