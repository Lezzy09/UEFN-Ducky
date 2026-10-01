/**
 * "Tour this workflow": Next / Back steps over one workflow's nodes, in the order they run.
 *
 * Step nodes follow their white wires from the starts; each value node is mentioned with
 * the step that uses it; what nobody uses (Preview, Save file) comes last. The editor's
 * ? menu and the AI's `tour_workflow(auto=true)` both use this.
 */
import type { AutomationGraphDto, AutomationGraphNodeDto, AutomationNodeDto } from "../types/panel";
import type { AgentWalkthroughStepInput } from "../walkthrough/agentWalkthrough";
import { nodeLabel } from "./NodeVisuals";
import { nodePins } from "./pins";

const MAX_STEPS = 30;
const ROUTE_NAMES: Record<string, string> = { main: "Next", true: "True", false: "False", each: "Each", done: "Done" };

export interface CurrentWorkflow {
  id: string;
  name: string;
  graph: AutomationGraphDto;
  byType: Map<string, AutomationNodeDto>;
}

let current: CurrentWorkflow | null = null;

/** The editor keeps this up to date with the workflow it has open. */
export function setCurrentWorkflow(next: CurrentWorkflow | null): void {
  current = next;
}

export function getCurrentWorkflow(): CurrentWorkflow | null {
  return current;
}

const list = (names: string[]) => names.filter(Boolean).join(", ");

/** The steps of a tour over `graph`, ready for the walkthrough runner. */
export function buildWorkflowTour(graph: AutomationGraphDto, byType: Map<string, AutomationNodeDto>): AgentWalkthroughStepInput[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const isStep = (node: AutomationGraphNodeDto) => nodePins(node, byType.get(node.type)).exec;
  const label = (id: string) => {
    const node = nodes.get(id);
    return node ? nodeLabel(node, byType.get(node.type)) : id;
  };
  const runEdges = graph.edges.filter((edge) => edge.kind !== "data" && nodes.has(edge.source) && nodes.has(edge.target));
  const dataEdges = graph.edges.filter((edge) => edge.kind === "data" && nodes.has(edge.source) && nodes.has(edge.target));
  const hasIncoming = new Set(runEdges.map((edge) => edge.target));
  const starts = graph.nodes.filter((node) => isStep(node) && !hasIncoming.has(node.id));

  // Step nodes in run order: breadth-first along white wires from each start.
  const order: string[] = [];
  const queue = starts.map((node) => node.id);
  while (queue.length) {
    const id = queue.shift()!;
    if (order.includes(id)) continue;
    order.push(id);
    for (const edge of runEdges) if (edge.source === id && !order.includes(edge.target)) queue.push(edge.target);
  }
  for (const node of graph.nodes) if (isStep(node) && !order.includes(node.id)) order.push(node.id);

  // Value nodes: shown with the first step that uses them (through other value nodes too).
  const feeds = (id: string, seen = new Set<string>()): string[] => {
    const out: string[] = [];
    for (const edge of dataEdges) {
      if (edge.target !== id || seen.has(edge.source)) continue;
      seen.add(edge.source);
      const source = nodes.get(edge.source)!;
      if (!isStep(source)) out.push(edge.source, ...feeds(edge.source, seen));
    }
    return out;
  };
  const mentioned = new Set<string>();
  const steps: AgentWalkthroughStepInput[] = [];
  for (const id of order) {
    const node = nodes.get(id)!;
    const meta = byType.get(node.type);
    const pins = nodePins(node, meta);
    const fed = feeds(id).filter((v) => !mentioned.has(v));
    fed.forEach((v) => mentioned.add(v));
    const routes = runEdges.filter((edge) => edge.source === id);
    const lines = [node.description || meta?.description || ""];
    if (pins.inputs.length) lines.push(`**Takes:** ${list(pins.inputs.map((pin) => pin.label))}`);
    if (pins.outputs.length) lines.push(`**Gives:** ${list(pins.outputs.map((pin) => pin.label))}`);
    if (fed.length) lines.push(`**Worked out first:** ${list(fed.map(label))}`);
    if (routes.some((edge) => edge.kind && edge.kind !== "main")) {
      lines.push(`**Then:** ${list(routes.map((edge) => `${ROUTE_NAMES[edge.kind || "main"] || edge.kind} → ${label(edge.target)}`))}`);
    } else if (routes.length) {
      lines.push(`**Then:** ${list(routes.map((edge) => label(edge.target)))}`);
    }
    steps.push({ target: `workflows.node.${id}`, title: label(id), body: lines.filter(Boolean).join("\n\n") });
  }
  // What nothing pulls (a Preview, Save file, a generator on its own) ends the run. Walk
  // each such chain node by node, in the order its values are worked out.
  const chain: string[] = [];
  const visit = (id: string) => {
    if (chain.includes(id) || mentioned.has(id)) return;
    for (const edge of dataEdges) {
      if (edge.target === id && !isStep(nodes.get(edge.source)!)) visit(edge.source);
    }
    chain.push(id);
  };
  for (const node of graph.nodes) {
    if (!isStep(node) && !dataEdges.some((edge) => edge.source === node.id)) visit(node.id);
  }
  for (const id of chain) {
    mentioned.add(id);
    const node = nodes.get(id)!;
    const meta = byType.get(node.type);
    const pins = nodePins(node, meta);
    const into = dataEdges.filter((edge) => edge.source === id).map((edge) => label(edge.target));
    const lines = [node.description || meta?.description || ""];
    if (pins.inputs.length) lines.push(`**Takes:** ${list(pins.inputs.map((pin) => pin.label))}`);
    if (pins.outputs.length) lines.push(`**Gives:** ${list(pins.outputs.map((pin) => pin.label))}`);
    lines.push(into.length ? `**Then:** ${list([...new Set(into)])}` : "**Runs on its own** at the end, with what is wired into it.");
    steps.push({ target: `workflows.node.${id}`, title: label(id), body: lines.filter(Boolean).join("\n\n") });
  }
  return steps.slice(0, MAX_STEPS);
}

/** The AI's own steps (`node_ids` / `group_id` / `target`) as walkthrough steps. */
export function aiTourSteps(raw: unknown): AgentWalkthroughStepInput[] {
  const out: AgentWalkthroughStepInput[] = [];
  for (const row of Array.isArray(raw) ? raw : []) {
    if (!row || typeof row !== "object") continue;
    const step = row as { node_ids?: unknown; group_id?: unknown; target?: unknown; title?: unknown; body?: unknown };
    const ids = Array.isArray(step.node_ids) ? step.node_ids.map(String).filter(Boolean) : [];
    const group = String(step.group_id || "").trim();
    const title = String(step.title || "").trim();
    const body = String(step.body || "").trim();
    if (ids.length) {
      out.push({ target: `workflows.node.${ids[0]}`, title, body, action: { id: "workflows.select", args: { node_ids: ids } } });
    } else if (group) {
      out.push({ target: `workflows.group.${group}`, title, body, action: { id: "workflows.select", args: { group_id: group } } });
    } else if (step.target && (typeof step.target === "string" || typeof step.target === "object")) {
      out.push({ target: step.target as AgentWalkthroughStepInput["target"], title, body });
    }
  }
  return out;
}

/** The first step opens the workflow, so a replay from chat lands in the right place. */
export function withOpenStep(steps: AgentWalkthroughStepInput[], workflowId: string): AgentWalkthroughStepInput[] {
  if (!steps.length) return steps;
  const [first, ...rest] = steps;
  // workflows.select opens the workflow itself when given its id.
  const action = first.action?.id === "workflows.select"
    ? { id: "workflows.select", args: { ...(first.action.args || {}), id: workflowId } }
    : { id: "workflows.open", args: { id: workflowId } };
  return [{ ...first, navigate: "workflows", action }, ...rest];
}
