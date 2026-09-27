import type { AutomationGraphDto, AutomationGraphNodeDto } from "../types/panel";

export const NODE_WIDTH = 200;
export const NODE_HEADER_HEIGHT = 76;
export const OVERVIEW_ZOOM = 0.7;

export function nodeWidth(node: AutomationGraphNodeDto, expanded: boolean): number {
  return expanded ? Math.min(720, Math.max(280, node.width || 320)) : NODE_WIDTH;
}

export function portPoint(node: AutomationGraphNodeDto, direction: "in" | "out", expanded: boolean) {
  return { x: node.x + (direction === "out" ? nodeWidth(node, expanded) : 0), y: node.y + NODE_HEADER_HEIGHT / 2 };
}

export function zoomAt(pan: { x: number; y: number }, zoom: number, next: number, point: { x: number; y: number }) {
  return { x: point.x - (point.x - pan.x) * next / zoom, y: point.y - (point.y - pan.y) * next / zoom };
}

/** Stable columns from graph dependencies; cycles get their own final column. */
export function arrangeGraph(graph: AutomationGraphDto, expandedId = ""): AutomationGraphDto {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const pending = new Set(ids);
  const columns = new Map<string, number>();
  while (pending.size) {
    const ready = [...pending].filter((id) => !graph.edges.some((e) => e.target === id && pending.has(e.source)));
    if (!ready.length) {
      const last = Math.max(-1, ...columns.values()) + 1;
      for (const id of pending) columns.set(id, last);
      break;
    }
    for (const id of ready) {
      const incoming = graph.edges.filter((e) => e.target === id && ids.has(e.source));
      columns.set(id, Math.max(-1, ...incoming.map((e) => columns.get(e.source) ?? -1)) + 1);
      pending.delete(id);
    }
  }
  const widths = new Map<number, number>();
  for (const node of graph.nodes) {
    const col = columns.get(node.id) || 0;
    widths.set(col, Math.max(widths.get(col) || 0, nodeWidth(node, node.id === expandedId)));
  }
  const positions = new Map<number, number>();
  let x = 0;
  for (const col of [...widths.keys()].sort((a, b) => a - b)) {
    positions.set(col, x);
    x += (widths.get(col) || NODE_WIDTH) + 80;
  }
  const rows = new Map<number, number>();
  return { ...graph, nodes: graph.nodes.map((node) => {
    const col = columns.get(node.id) || 0;
    const row = rows.get(col) || 0;
    rows.set(col, row + (node.id === expandedId ? 504 : 140));
    return { ...node, x: positions.get(col) || 0, y: row };
  }) };
}
