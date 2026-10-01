// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { AutomationNodeDto } from "../types/panel";
import { HOST_TOUR_CATALOG_IDS } from "../walkthrough/WalkthroughService";
import { setCurrentWorkflow } from "./workflowTour";
import { FIRST_BUILD_TEMPLATE, WORKFLOWS_EDITOR_TOUR, WORKFLOWS_FIRST_BUILD_TOUR, WORKFLOWS_INTRO_TOUR, WORKFLOWS_TOURS } from "./workflowsTours";

const SOURCES = ["AutomationsView.tsx", "WorkflowInspector.tsx", "WorkflowList.tsx", "AutomationTemplatePicker.tsx", "NodeSettings.tsx"]
  .map((name) => readFileSync(join(process.cwd(), "src", "automations", name), "utf8"))
  .join("\n");

/** Dynamic ids are registered by a pattern in the code; fixed ones appear as written. */
const PATTERNS: Array<[string, string]> = [
  ["workflows.node.", "`workflows.node.${"],
  ["workflows.wire.", "data-aw-wire"],
  ["workflows.template.", "`workflows.template.${"],
  ["workflows.details.field.", "data-aw-field"],
  ["workflows.list.new.", "`workflows.list.new.${"],
];

function registeredInCode(id: string): boolean {
  if (id === `workflows.template.${FIRST_BUILD_TEMPLATE}`) return SOURCES.includes(PATTERNS[2][1]);
  const pattern = PATTERNS.find(([prefix]) => id.startsWith(prefix) && id !== prefix.slice(0, -1));
  if (pattern && !SOURCES.includes(`"${id}"`)) return SOURCES.includes(pattern[1]);
  return SOURCES.includes(`"${id}"`);
}

const openWorkflow = () => setCurrentWorkflow({
  id: "wf1",
  name: "Demo",
  byType: new Map<string, AutomationNodeDto>([["start.manual", { type: "start.manual", label: "Manual", group: "Starting" }]]),
  graph: {
    nodes: [{ id: "s", type: "start.manual", x: 0, y: 0, config: {} }, { id: "w", type: "flow.wait", x: 0, y: 0, config: {} }],
    edges: [{ source: "s", target: "w", kind: "main" }],
  },
});

afterEach(() => setCurrentWorkflow(null));

describe("Workflows tours", () => {
  it("point only at things the editor really registers", () => {
    openWorkflow();
    const steps = WORKFLOWS_TOURS.flatMap((tour) => tour.resolveSteps!());
    const missing = steps.map((step) => step.target).filter((id) => !registeredInCode(id));
    expect(missing).toEqual([]);
  });

  it("adapt to what's open: a node and the toolbar only with a workflow open", () => {
    const empty = WORKFLOWS_INTRO_TOUR.resolveSteps!().map((step) => step.target);
    expect(empty).not.toContain("workflows.toolbar.run");
    expect(empty[0]).toBe("workflows.list");
    expect(empty.at(-1)).toBe("workflows.help");
    openWorkflow();
    const open = WORKFLOWS_INTRO_TOUR.resolveSteps!().map((step) => step.target);
    expect(open).toContain("workflows.node.s");
    expect(open).toContain("workflows.toolbar.run");
    expect(WORKFLOWS_EDITOR_TOUR.resolveSteps!().map((step) => step.target)).toContain("workflows.wire.s>w:main");
  });

  it("build-your-first is hands-on and uses the free Title card", () => {
    const steps = WORKFLOWS_FIRST_BUILD_TOUR.resolveSteps!();
    expect(steps[1].target).toBe("workflows.template.builtin:pipe-title-card");
    expect(steps.filter((step) => step.advance === "require_click").map((step) => step.target)).toEqual([
      expect.stringMatching(/^workflows\.(empty|list)\.new/), "workflows.template.builtin:pipe-title-card", "workflows.templates.create", "workflows.toolbar.run",
    ]);
  });

  it("are listed in Settings → Walkthrough for replay", () => {
    for (const tour of WORKFLOWS_TOURS) expect(HOST_TOUR_CATALOG_IDS as readonly string[]).toContain(tour.id);
  });
});
