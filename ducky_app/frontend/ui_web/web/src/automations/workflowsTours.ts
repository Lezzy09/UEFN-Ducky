/**
 * Workflows tours: the intro that runs the first time Workflows opens, a hands-on
 * "Build your first workflow" (the free Title card template, no credits), and editor
 * basics. Steps adapt to what is on screen (no workflows yet, a workflow open…).
 */
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import { getTargetElement } from "../ui-targets/registry";
import { isShown, runUiAction } from "../ui-targets/resolve";
import type { WalkthroughDef, WalkthroughStep } from "../walkthrough/types";
import { getCurrentWorkflow } from "./workflowTour";

export const WORKFLOWS_INTRO_TOUR_ID = "workflows.intro";
export const WORKFLOWS_FIRST_BUILD_TOUR_ID = "workflows.first_build";
export const WORKFLOWS_EDITOR_TOUR_ID = "workflows.editor";
export const FIRST_BUILD_TEMPLATE = "builtin:pipe-title-card";

const sleep = (ms: number) => new Promise<void>((r) => globalThis.setTimeout(r, ms));
const on = (id: string) => {
  const el = getTargetElement(id);
  return !!el && isShown(el);
};
/** The first of these that is on screen (else the first). */
const firstShown = (...ids: string[]) => ids.find(on) || ids[0];
const NEW_BUTTONS = ["workflows.empty.new", "workflows.list.new", "workflows.section.new.local", "workflows.list.new.local"];

const next = (target: string, title: string, body: string, onEnter?: () => Promise<void> | void): WalkthroughStep => ({ target, title, body, advance: "next", onEnter });
const click = (target: string, title: string, body: string, onEnter?: () => Promise<void> | void): WalkthroughStep => ({ target, title, body, advance: "require_click", onEnter });

async function openWorkflows(): Promise<void> {
  requestOpenWorkflowsTab();
  await sleep(350);
}

/** The first node that runs (a start, else the first step node). */
function firstNode(): string {
  const current = getCurrentWorkflow();
  if (!current?.graph.nodes.length) return "";
  const runTargets = new Set(current.graph.edges.filter((edge) => edge.kind !== "data").map((edge) => edge.target));
  const start = current.graph.nodes.find((node) => !runTargets.has(node.id) && current.byType.get(node.type)?.exec !== false);
  return (start || current.graph.nodes[0]).id;
}

/** The first white wire, as a target id. */
function firstWire(): string {
  const edge = getCurrentWorkflow()?.graph.edges.find((e) => e.kind !== "data");
  return edge ? `workflows.wire.${edge.source}>${edge.target}:${edge.kind || "main"}` : "";
}

function introSteps(): WalkthroughStep[] {
  const open = !!getCurrentWorkflow();
  const steps: WalkthroughStep[] = [
    next("workflows.list", "Your workflows",
      "A workflow runs steps for you: make a picture, test your island, post a report. **Local** ones stay on this PC; **team** ones are shared. Right-click one to rename, switch it off, duplicate or delete it.",
      openWorkflows),
    next(firstShown(...NEW_BUTTONS), "New workflow", "Start from a ready-made template (pictures, 3D, characters, play tests…) or a blank canvas."),
  ];
  if (on("workflows.empty.picks")) {
    steps.push(next("workflows.empty.picks", "One-click starts", "These templates are ready to run. Pick one to see a whole workflow."));
  }
  steps.push(
    next("workflows.canvas", "The canvas",
      "Drag empty space to move around, scroll to zoom, right-click to add a node. **White wires** decide what runs next; **colored wires** carry values (text, pictures, 3D models) from one node to another."),
    next("workflows.add", "Add nodes", "Every node, grouped and searchable: inputs, AI, images, 3D, UEFN, play tests, logic, loops."),
  );
  const node = firstNode();
  if (node) {
    steps.push(next(`workflows.node.${node}`, "A node",
      "Colored pins take values in on the left and give values out on the right. Steps also have white pins that run them in order. Click a node to open its details."));
  }
  if (open) {
    steps.push(
      next("workflows.toolbar.run", "Test", "Run it now. Each node lights up while it works."),
      next("workflows.log", "Run log", "What each step did, with the pictures and files it made."),
      next("workflows.toolbar.onoff", "On / off", "A workflow with a schedule only runs while it's on."),
      next("workflows.toolbar.history", "History", "Every save is kept. Bring an older one back in one click."),
    );
  }
  steps.push(next("workflows.help", "Tours any time",
    "This **?** replays this tour, walks you through building your first workflow, or tours the workflow you have open. You can also ask Ducky in chat to find, build, explain or run a workflow, and to show you any part of it."));
  return steps;
}

function firstBuildSteps(): WalkthroughStep[] {
  return [
    click(firstShown(...NEW_BUTTONS), "Click New workflow", "We'll make a title picture. It's free and runs on this PC.", async () => {
      await openWorkflows();
      await runUiAction("workflows.close_overlays");
    }),
    click(`workflows.template.${FIRST_BUILD_TEMPLATE}`, "Pick Title card", "It draws your text onto a 1920×1080 picture, for loading screens and signs.", async () => {
      await sleep(250);
      if (!on(`workflows.template.${FIRST_BUILD_TEMPLATE}`)) await runUiAction("workflows.templates", { shelf: "Images" });
      await sleep(300);
    }),
    click("workflows.templates.create", "Create it", "Your workflow opens on the canvas, ready to run."),
    next("workflows.node.q", "The title", "This node holds the text that goes on the picture.", async () => {
      await sleep(600);
      await runUiAction("workflows.select", { node_ids: ["q"] });
      await sleep(300);
    }),
    next("workflows.details.field.value", "Type your title", "Change the text here. Anything you type is drawn onto the picture."),
    click("workflows.toolbar.run", "Press Test", "Run it now and watch each node light up."),
    next("workflows.node.p", "Your picture", "When the run finishes, the picture shows on this Preview card. Click it to open it full size.", () => sleep(1500)),
    next("workflows.log", "Run log", "What each step did. Open it any time to see a run."),
    next("workflows.toolbar.save", "That's a workflow", "Save keeps it in your list. Ducky can build much bigger ones: ask it in chat, like “make a workflow that turns a prompt into a 3D model in UEFN”."),
  ];
}

function editorSteps(): WalkthroughStep[] {
  const node = firstNode();
  const wire = firstWire();
  const steps: WalkthroughStep[] = [
    next("workflows.canvas", "Canvas", "Space or the hand tool moves around. Drag a box on empty space to select several nodes.", openWorkflows),
  ];
  if (node) {
    steps.push(
      next(`workflows.node.${node}`, "Pins", "The colors tell what a pin carries: text, number, yes/no, picture, 3D model… A wire only fits pins that match."),
    );
  }
  if (wire) {
    steps.push(next(wire, "Wires", "Click a wire to pick its route: Next, True / False after an If, Each / Done after a loop."));
  }
  if (node) {
    steps.push(
      next("workflows.details", "Details", "Everything about the picked node: its settings, the values going in, what came out last run.", async () => {
        await runUiAction("workflows.select", { node_ids: [node] });
        await sleep(300);
      }),
      next("workflows.details.run", "Run this node", "Runs just this node with what came in last time. Handy while you tune one step."),
      next("workflows.details.lock", "Lock", "A locked node can't be moved or changed, by you or by Ducky, until you unlock it."),
    );
  }
  steps.push(
    next("workflows.outline", "Outline", "Every node in a list. Pick one to jump to it."),
    next("workflows.fit", "Fit", "Fit the whole workflow on screen (F)."),
  );
  return steps;
}

export const WORKFLOWS_INTRO_TOUR: WalkthroughDef = {
  id: WORKFLOWS_INTRO_TOUR_ID,
  title: "Workflows",
  description: "Runs the first time you open Workflows: the list, the canvas, nodes and wires, Test, the run log.",
  autoStart: "never",
  steps: introSteps(),
  resolveSteps: introSteps,
};

export const WORKFLOWS_FIRST_BUILD_TOUR: WalkthroughDef = {
  id: WORKFLOWS_FIRST_BUILD_TOUR_ID,
  title: "Build your first workflow",
  description: "Hands-on: make a title picture from a template, change the text, run it. Free.",
  autoStart: "never",
  steps: firstBuildSteps(),
  resolveSteps: firstBuildSteps,
};

export const WORKFLOWS_EDITOR_TOUR: WalkthroughDef = {
  id: WORKFLOWS_EDITOR_TOUR_ID,
  title: "Workflow editor basics",
  description: "Pins and their colors, wire routes, details, Run this node, locks, outline.",
  autoStart: "never",
  steps: editorSteps(),
  resolveSteps: editorSteps,
};

export const WORKFLOWS_TOURS = [WORKFLOWS_INTRO_TOUR, WORKFLOWS_FIRST_BUILD_TOUR, WORKFLOWS_EDITOR_TOUR];
