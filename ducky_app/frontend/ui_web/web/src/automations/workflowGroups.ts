import type { AutomationGraphDto, AutomationGraphGroupDto, AutomationGraphNodeDto } from "../types/panel";

export type GraphRect = { x: number; y: number; width: number; height: number };
type Size = (node: AutomationGraphNodeDto) => { width: number; height: number };

const PAD = 24;

export function selectionRect(a: { x: number; y: number }, b: { x: number; y: number }): GraphRect {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
}

export function intersects(a: GraphRect, b: GraphRect): boolean {
  return a.x <= b.x + b.width && a.x + a.width >= b.x && a.y <= b.y + b.height && a.y + a.height >= b.y;
}

function childrenOf(groups: AutomationGraphGroupDto[], id: string) {
  return groups.filter((group) => group.parent_id === id);
}

/** Every node inside a group, including the nodes of the groups nested in it. */
export function groupMembers(groups: AutomationGraphGroupDto[], id: string, seen = new Set<string>()): string[] {
  const group = groups.find((item) => item.id === id);
  if (!group || seen.has(id)) return [];
  seen.add(id);
  return [...group.node_ids, ...childrenOf(groups, id).flatMap((child) => groupMembers(groups, child.id, seen))];
}

/** 0 for a top-level box, 1 inside one box, and so on. */
export function groupDepth(groups: AutomationGraphGroupDto[], id: string): number {
  let depth = 0;
  const seen = new Set([id]);
  for (let at = groups.find((group) => group.id === id)?.parent_id; at && !seen.has(at); at = groups.find((group) => group.id === at)?.parent_id) {
    seen.add(at);
    depth++;
  }
  return depth;
}

/** The box around a group's nodes and nested boxes. ``titleSpace`` (graph units) leaves
 *  room above each nested box for its title, which sits outside its own box. */
export function groupBounds(group: AutomationGraphGroupDto, nodes: AutomationGraphNodeDto[], size: Size, groups: AutomationGraphGroupDto[] = [], titleSpace = 0, seen = new Set<string>()): GraphRect | null {
  if (seen.has(group.id)) return null;
  seen.add(group.id);
  const rects: GraphRect[] = nodes.filter((node) => group.node_ids.includes(node.id)).map((node) => ({ x: node.x, y: node.y, ...size(node) }));
  for (const child of childrenOf(groups, group.id)) {
    const box = groupBounds(child, nodes, size, groups, titleSpace, seen);
    if (box) rects.push({ x: box.x, y: box.y - titleSpace, width: box.width, height: box.height + titleSpace });
  }
  if (!rects.length) return null;
  const x = Math.min(...rects.map((rect) => rect.x)) - PAD;
  const y = Math.min(...rects.map((rect) => rect.y)) - PAD;
  return {
    x, y,
    width: Math.max(...rects.map((rect) => rect.x + rect.width)) + PAD - x,
    height: Math.max(...rects.map((rect) => rect.y + rect.height)) + PAD - y,
  };
}

function withParent(group: AutomationGraphGroupDto, parent: string | undefined): AutomationGraphGroupDto {
  const { parent_id: _old, ...rest } = group;
  return parent ? { ...rest, parent_id: parent } : rest;
}

/** Remove missing or repeated memberships, broken parents and loops, and boxes left
 *  with no nodes and no nested boxes; a one-node group remains valid. */
export function cleanGroups(graph: AutomationGraphDto): AutomationGraphDto {
  if (!graph.groups) return graph;
  const ids = new Set(graph.nodes.map((node) => node.id));
  const used = new Set<string>();
  let groups = graph.groups.map((group) => ({ ...group, node_ids: group.node_ids.filter((id) => {
    if (!ids.has(id) || used.has(id)) return false;
    used.add(id);
    return true;
  }) }));
  const known = new Map(groups.map((group) => [group.id, group]));
  groups = groups.map((group) => {
    const seen = new Set([group.id]);
    let at = group.parent_id;
    while (at && known.has(at) && !seen.has(at)) { seen.add(at); at = known.get(at)!.parent_id; }
    if (at) { const fixed = withParent(group, undefined); known.set(group.id, fixed); return fixed; }
    return group;
  });
  for (;;) {
    const parents = new Set(groups.map((group) => group.parent_id).filter(Boolean));
    const kept = groups.filter((group) => group.node_ids.length > 0 || parents.has(group.id));
    if (kept.length === groups.length) break;
    groups = kept;
  }
  return { ...graph, groups };
}

/** Locked: the group, or any box around it, can't be moved or changed. */
export function groupLocked(groups: AutomationGraphGroupDto[], id: string): boolean {
  const seen = new Set<string>();
  for (let at: string | undefined = id; at && !seen.has(at); at = groups.find((group) => group.id === at)?.parent_id) {
    seen.add(at);
    if (groups.find((group) => group.id === at)?.locked) return true;
  }
  return false;
}

/** Locked: the node itself, or any group it sits in. */
export function nodeLocked(graph: AutomationGraphDto, id: string): boolean {
  if (graph.nodes.find((node) => node.id === id)?.locked) return true;
  const groups = graph.groups || [];
  const home = groups.find((group) => group.node_ids.includes(id));
  return !!home && groupLocked(groups, home.id);
}

/** Box colours a group can take (the backend keeps the same list). */
export const GROUP_COLORS = ["", "red", "amber", "green", "blue", "purple"] as const;

/** Ungroup one box: its nodes and nested boxes move to the box around it. */
export function removeGroup(graph: AutomationGraphDto, id: string): AutomationGraphDto {
  const groups = graph.groups || [];
  const group = groups.find((item) => item.id === id);
  if (!group) return graph;
  const next = groups.filter((item) => item.id !== id).map((item) => {
    if (item.parent_id === id) return withParent(item, group.parent_id);
    return item.id === group.parent_id ? { ...item, node_ids: [...item.node_ids, ...group.node_ids] } : item;
  });
  return cleanGroups({ ...graph, groups: next });
}

/** Remove nodes with their connections; groups left empty go too. */
export function deleteNodes(graph: AutomationGraphDto, ids: string[]): AutomationGraphDto {
  const gone = new Set(ids);
  if (!graph.nodes.some((node) => gone.has(node.id))) return graph;
  return cleanGroups({ ...graph, nodes: graph.nodes.filter((node) => !gone.has(node.id)), edges: graph.edges.filter((edge) => !gone.has(edge.source) && !gone.has(edge.target)) });
}

/** Ctrl+Shift+G. Groups whose every node is selected open up one level (their
 *  nodes and boxes move to the box around them); other selected nodes step out
 *  of their box into the one around it. */
export function ungroupNodes(graph: AutomationGraphDto, selected: string[]): AutomationGraphDto {
  const groups = graph.groups || [];
  const picked = new Set(selected);
  if (!groups.some((group) => group.node_ids.some((id) => picked.has(id)))) return graph;
  const whole = new Set(groups.filter((group) => { const members = groupMembers(groups, group.id); return members.length > 0 && members.every((id) => picked.has(id)); }).map((group) => group.id));
  const opened = new Set([...whole].filter((id) => !whole.has(groups.find((group) => group.id === id)?.parent_id || "")));
  const inOpened = new Set([...opened].flatMap((id) => groupMembers(groups, id)));
  const parentOf = new Map(groups.map((group) => [group.id, group.parent_id]));
  const target = (id: string | undefined) => { while (id && opened.has(id)) id = parentOf.get(id); return id; };
  const moving = new Map<string, string | undefined>();  // node -> the box it lands in
  for (const group of groups) {
    for (const id of group.node_ids) {
      if (opened.has(group.id)) moving.set(id, target(group.id));
      else if (picked.has(id) && !inOpened.has(id)) moving.set(id, target(group.parent_id));
    }
  }
  const next = groups.filter((group) => !opened.has(group.id)).map((group) => {
    const node_ids = [...group.node_ids.filter((id) => !moving.has(id)), ...[...moving].filter(([, to]) => to === group.id).map(([id]) => id)];
    const parent = target(group.parent_id);
    return withParent({ ...group, node_ids }, parent);
  });
  return cleanGroups({ ...graph, groups: next });
}

/** Ctrl+G. Selected whole groups nest inside the new group, loose nodes move into it,
 *  and it sits inside the innermost group that holds the whole selection. */
export function groupNodes(graph: AutomationGraphDto, selected: string[], id: string): AutomationGraphDto {
  const members = graph.nodes.filter((node) => selected.includes(node.id)).map((node) => node.id);
  if (members.length < 2) return graph;
  const groups = graph.groups || [];
  const picked = new Set(members);
  const full = new Map(groups.map((group) => [group.id, groupMembers(groups, group.id)]));
  if (groups.some((group) => full.get(group.id)!.length === members.length && full.get(group.id)!.every((member) => picked.has(member)))) return graph;
  const container = groups.filter((group) => members.every((member) => full.get(group.id)!.includes(member)))
    .sort((a, b) => groupDepth(groups, b.id) - groupDepth(groups, a.id))[0];
  const whole = new Set(groups.filter((group) => group.id !== container?.id && full.get(group.id)!.length > 0 && full.get(group.id)!.every((member) => picked.has(member))).map((group) => group.id));
  const nested = [...whole].filter((gid) => !whole.has(groups.find((group) => group.id === gid)?.parent_id || ""));
  const inNested = new Set(nested.flatMap((gid) => full.get(gid)!));
  const loose = members.filter((member) => !inNested.has(member));
  const names = new Set(groups.map((group) => group.name));
  let name = "Group";
  for (let number = 2; names.has(name); number++) name = `Group ${number}`;
  const next = groups.map((group) => {
    const kept = { ...group, node_ids: group.node_ids.filter((member) => !loose.includes(member)) };
    return nested.includes(group.id) ? withParent(kept, id) : kept;
  });
  return cleanGroups({ ...graph, groups: [...next, withParent({ id, name, node_ids: loose }, container?.id)] });
}
