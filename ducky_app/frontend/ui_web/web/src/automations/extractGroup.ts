import type { AutomationGraphDto, AutomationGraphEdgeDto, AutomationGraphGroupDto, AutomationGraphNodeDto } from "../types/panel";
import { cleanGroups, groupMembers } from "./workflowGroups";

export type GroupExtraction =
  | { ok: false; error: string }
  | {
      ok: true;
      /** The new workflow: Inputs → the group's nodes → Return. */
      child: AutomationGraphDto;
      /** This workflow with the group replaced by a Run workflow node for ``workflowId``. */
      parent: (workflowId: string, callId: string, label: string) => AutomationGraphDto;
    };

function descendants(groups: AutomationGraphGroupDto[], id: string): AutomationGraphGroupDto[] {
  const children = groups.filter((group) => group.parent_id === id);
  return [...children, ...children.flatMap((child) => descendants(groups, child.id))];
}

function freshId(prefix: string, taken: Set<string>): string {
  let id = prefix;
  for (let n = 2; taken.has(id); n++) id = `${prefix}${n}`;
  taken.add(id);
  return id;
}

/** Plan turning a group into a reusable workflow that runs exactly where the group was.
 *  The Run workflow node shares this run's data, so the moved nodes see and set the same
 *  fields; a path that left the group reaches Return, and a path that ended inside it
 *  still ends the caller's path. Refuses what one node can't stand in for. */
export function planGroupExtraction(graph: AutomationGraphDto, groupId: string, isStarter: (node: AutomationGraphNodeDto) => boolean): GroupExtraction {
  const groups = graph.groups || [];
  if (!groups.some((group) => group.id === groupId)) return { ok: false, error: "That group no longer exists." };
  const inside = new Set(groupMembers(groups, groupId));
  const members = graph.nodes.filter((node) => inside.has(node.id));
  if (!members.length) return { ok: false, error: "That group has no nodes." };
  if (members.some(isStarter)) return { ok: false, error: "Starts (Chat input, schedules, triggers, Inputs) can't move into another workflow. Take them out of the group first." };
  const incoming = graph.edges.filter((edge) => !inside.has(edge.source) && inside.has(edge.target));
  const outgoing = graph.edges.filter((edge) => inside.has(edge.source) && !inside.has(edge.target));
  if (outgoing.some((edge) => edge.kind === "each")) return { ok: false, error: "A For each wire leaves this group, so those steps would run once instead of once per item. Put the loop's steps in the group too." };
  // Every way out must lead to the same next steps: one node after the group can't pick between them.
  const exits = new Map<string, Set<string>>();
  for (const edge of outgoing) {
    const key = `${edge.source}\n${edge.kind || "main"}`;
    exits.set(key, (exits.get(key) || new Set()).add(edge.target));
  }
  if (new Set([...exits.values()].map((targets) => [...targets].sort().join("\n"))).size > 1) {
    return { ok: false, error: "Paths leave this group for different next steps. Join them into one step after the group first." };
  }
  const targets = [...new Set(outgoing.map((edge) => edge.target))];

  const taken = new Set(members.map((node) => node.id));
  const inputId = freshId("inputs", taken);
  const returnId = freshId("return", taken);
  const minX = Math.min(...members.map((node) => node.x));
  const minY = Math.min(...members.map((node) => node.y));
  const maxX = Math.max(...members.map((node) => node.x));
  const dx = 280 - minX;
  const dy = -minY;
  const hasIncoming = new Set(graph.edges.map((edge) => edge.target));
  let entries = [...new Set([...incoming.map((edge) => edge.target), ...members.filter((node) => !hasIncoming.has(node.id)).map((node) => node.id)])];
  if (!entries.length) entries = [members[0].id];
  const avgY = (ids: string[]) => ids.length ? members.filter((node) => ids.includes(node.id)).reduce((sum, node) => sum + node.y, 0) / ids.length + dy : 0;
  const inner = descendants(groups, groupId);
  const child: AutomationGraphDto = {
    nodes: [
      { id: inputId, type: "flow.input", x: 0, y: avgY(entries), config: { inputs: [] }, label: "Inputs", description: "" },
      ...members.map((node) => ({ ...node, x: node.x + dx, y: node.y + dy })),
      ...(outgoing.length ? [{ id: returnId, type: "flow.output", x: maxX + dx + 360, y: avgY([...new Set(outgoing.map((edge) => edge.source))]), config: { outputs: [] }, label: "Return", description: "" }] : []),
    ],
    edges: [
      ...entries.map((target): AutomationGraphEdgeDto => ({ source: inputId, target, kind: "main" })),
      ...graph.edges.filter((edge) => inside.has(edge.source) && inside.has(edge.target)),
      ...[...exits.keys()].map((key): AutomationGraphEdgeDto => { const [source, kind] = key.split("\n"); return { source, target: returnId, kind }; }),
    ],
    groups: inner.map((group) => {
      if (group.parent_id !== groupId) return group;
      const { parent_id: _dropped, ...top } = group;
      return top;
    }),
  };

  const parent = (workflowId: string, callId: string, label: string): AutomationGraphDto => {
    const gone = new Set([groupId, ...inner.map((group) => group.id)]);
    const outer = groups.find((group) => group.id === groupId)?.parent_id;
    const seen = new Set<string>();
    const into = incoming.filter((edge) => { const key = `${edge.source}\n${edge.kind}`; if (seen.has(key)) return false; seen.add(key); return true; });
    return cleanGroups({
      nodes: [...graph.nodes.filter((node) => !inside.has(node.id)),
        { id: callId, type: "workflow.call", x: minX, y: minY, label, description: "", config: { workflow_id: workflowId, args: {}, share: true } }],
      edges: [
        ...graph.edges.filter((edge) => !inside.has(edge.source) && !inside.has(edge.target)),
        ...into.map((edge) => ({ source: edge.source, target: callId, kind: edge.kind })),
        ...targets.map((target) => ({ source: callId, target, kind: "main" })),
      ],
      groups: groups.filter((group) => !gone.has(group.id)).map((group) => group.id === outer ? { ...group, node_ids: [...group.node_ids, callId] } : group),
    });
  };
  return { ok: true, child, parent };
}
