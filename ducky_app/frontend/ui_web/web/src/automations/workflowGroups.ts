import type { AutomationGraphDto, AutomationGraphGroupDto, AutomationGraphNodeDto } from "../types/panel";

export type GraphRect = { x: number; y: number; width: number; height: number };

export function selectionRect(a: { x: number; y: number }, b: { x: number; y: number }): GraphRect {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
}

export function intersects(a: GraphRect, b: GraphRect): boolean {
  return a.x <= b.x + b.width && a.x + a.width >= b.x && a.y <= b.y + b.height && a.y + a.height >= b.y;
}

export function groupBounds(group: AutomationGraphGroupDto, nodes: AutomationGraphNodeDto[], size: (node: AutomationGraphNodeDto) => { width: number; height: number }): GraphRect | null {
  const members = nodes.filter((node) => group.node_ids.includes(node.id));
  if (!members.length) return null;
  const x = Math.min(...members.map((node) => node.x)) - 24;
  const y = Math.min(...members.map((node) => node.y)) - 24;
  return {
    x, y,
    width: Math.max(...members.map((node) => node.x + size(node).width)) + 24 - x,
    height: Math.max(...members.map((node) => node.y + size(node).height)) + 24 - y,
  };
}

/** Remove missing memberships and empty boxes; a one-node group remains valid. */
export function cleanGroups(graph: AutomationGraphDto): AutomationGraphDto {
  if (!graph.groups) return graph;
  const ids = new Set(graph.nodes.map((node) => node.id));
  const used = new Set<string>();
  const groups = graph.groups.map((group) => ({ ...group, node_ids: group.node_ids.filter((id) => {
    if (!ids.has(id) || used.has(id)) return false;
    used.add(id);
    return true;
  }) })).filter((group) => group.node_ids.length > 0);
  return { ...graph, groups };
}

export function ungroupNodes(graph: AutomationGraphDto, selected: string[]): AutomationGraphDto {
  const ids = new Set(selected);
  if (!graph.groups?.some((group) => group.node_ids.some((id) => ids.has(id)))) return graph;
  return cleanGroups({ ...graph, groups: graph.groups.map((group) => ({ ...group, node_ids: group.node_ids.filter((id) => !ids.has(id)) })) });
}

export function groupNodes(graph: AutomationGraphDto, selected: string[], id: string): AutomationGraphDto {
  const members = graph.nodes.filter((node) => selected.includes(node.id)).map((node) => node.id);
  if (members.length < 2) return graph;
  if (graph.groups?.some((group) => group.node_ids.length === members.length && group.node_ids.every((member) => members.includes(member)))) return graph;
  const next = ungroupNodes(graph, members);
  const names = new Set(next.groups?.map((group) => group.name));
  let name = "Group";
  for (let number = 2; names.has(name); number++) name = `Group ${number}`;
  return { ...next, groups: [...(next.groups || []), { id, name, node_ids: members }] };
}
