import { useEffect, useState, type ReactNode } from "react";
import { EditorTabHoverCardShell } from "../components/editor/EditorTabHoverCardShell";
import { getApi } from "../hooks/usePanelApi";
import type { AutomationGraphDto, AutomationSummaryDto } from "../types/panel";
import { nodeRole } from "./NodeVisuals";
import { NODE_HEIGHT, NODE_TITLE_HEIGHT, NODE_WIDTH, portPoint, wirePath } from "./graphGeometry";
import { groupBounds, groupDepth } from "./workflowGroups";

/** Graphs fetched for previews, until the workflow changes (its `updated` time). */
const previews = new Map<string, { key: string; graph: Promise<AutomationGraphDto | null> }>();

function loadPreview(row: AutomationSummaryDto): Promise<AutomationGraphDto | null> {
  const key = `${row.updated || 0}:${row.node_count || 0}`;
  const hit = previews.get(row.id);
  if (hit && hit.key === key) return hit.graph;
  const graph = Promise.resolve(getApi()?.get_workflow?.(row.id))
    .then((res) => res?.workflow?.graph || null)
    .catch(() => null);
  previews.set(row.id, { key, graph });
  return graph;
}

const ROLE_COLOR: Record<string, string> = {
  starter: "var(--wf-node-starter)", end: "var(--wf-node-end)", agent: "var(--wf-node-agent)",
  function: "var(--wf-node-function)", logic: "var(--wf-node-logic)", action: "var(--wf-node-action)", input: "var(--wf-node-input)",
};
const tint = (color: string | undefined, role: string) => color ? `var(--${color})` : ROLE_COLOR[role] || ROLE_COLOR.action;

/** The workflow in miniature: its groups, wires and cards, colored as on the canvas. */
export function WorkflowMiniature({ graph }: { graph: AutomationGraphDto }) {
  const size = () => ({ width: NODE_WIDTH, height: NODE_HEIGHT });
  const groups = graph.groups || [];
  const boxes = groups.map((group) => ({ group, depth: groupDepth(groups, group.id), bounds: groupBounds(group, graph.nodes, size, groups, 40) }))
    .filter((box) => box.bounds).sort((a, b) => a.depth - b.depth);
  const rects = [...graph.nodes.map((node) => ({ x: node.x, y: node.y, width: NODE_WIDTH, height: NODE_HEIGHT })), ...boxes.map((box) => box.bounds!)];
  if (!rects.length) return <div className="aw-mini aw-mini--empty">No nodes yet</div>;
  const pad = 30;
  const x = Math.min(...rects.map((rect) => rect.x)) - pad;
  const y = Math.min(...rects.map((rect) => rect.y)) - pad;
  const width = Math.max(...rects.map((rect) => rect.x + rect.width)) + pad - x;
  const height = Math.max(...rects.map((rect) => rect.y + rect.height)) + pad - y;
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  return (
    <svg className="aw-mini" viewBox={`${x} ${y} ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {boxes.map(({ group, bounds }) => <rect key={group.id} className="aw-mini-group" x={bounds!.x} y={bounds!.y} width={bounds!.width} height={bounds!.height} rx={14}
        style={{ fill: group.color ? `color-mix(in srgb, var(--${group.color}) 14%, transparent)` : undefined, stroke: group.color ? `var(--${group.color})` : undefined }} />)}
      {graph.edges.map((edge, index) => {
        const a = byId.get(edge.source), b = byId.get(edge.target);
        if (!a || !b) return null;
        const from = portPoint(a, "out"), to = portPoint(b, "in");
        return <path key={index} className="aw-mini-wire" d={wirePath(from.x, from.y, to.x, to.y)} style={{ stroke: tint(a.color, nodeRole(a)) }} />;
      })}
      {graph.nodes.map((node) => (
        <g key={node.id}>
          <rect className="aw-mini-card" x={node.x} y={node.y} width={NODE_WIDTH} height={NODE_HEIGHT} rx={12} />
          <rect x={node.x} y={node.y} width={NODE_WIDTH} height={NODE_TITLE_HEIGHT} rx={12} style={{ fill: tint(node.color, nodeRole(node)) }} />
        </g>
      ))}
    </svg>
  );
}

function CardBody({ row, icon, onOpen }: { row: AutomationSummaryDto; icon: ReactNode; onOpen: () => void }) {
  const [graph, setGraph] = useState<AutomationGraphDto | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    void loadPreview(row).then((value) => { if (alive) setGraph(value); });
    return () => { alive = false; };
  }, [row.id, row.updated, row.node_count]);
  const nodes = row.node_count ?? graph?.nodes.length ?? 0;
  const where = [row.owner?.kind === "team" ? row.owner.label : "Local", row.folder].filter(Boolean).join(" / ");
  return (
    <button type="button" className="aw-hover-card" onClick={onOpen} title="Open this workflow">
      <div className="editor-tab-hover-card-header">
        <div className="editor-tab-hover-card-icon aw-hover-card-icon">{icon}</div>
        <div className="editor-tab-hover-card-titles">
          <div className="editor-tab-hover-card-name">{row.name || "Untitled"}</div>
          <div className="editor-tab-hover-card-subtitle">{nodes} node{nodes === 1 ? "" : "s"} · {row.trigger?.label || "Manual"}</div>
        </div>
      </div>
      <div className="aw-hover-card-preview">
        {graph === undefined ? <div className="aw-mini aw-mini--empty">Loading…</div> : graph ? <WorkflowMiniature graph={graph} /> : <div className="aw-mini aw-mini--empty">No preview</div>}
      </div>
      {row.description ? <p className="aw-hover-card-desc">{row.description}</p> : null}
      <div className="aw-hover-card-foot">
        <span className={`aw-list-state${row.enabled ? " is-on" : ""}`} aria-hidden="true" />
        <span>{row.enabled ? "On" : "Off"}</span>
        <span className="aw-hover-card-where">{where}</span>
      </div>
    </button>
  );
}

/** Hovering a workflow in the list shows a card beside it, like the Duckies list: its name,
 *  what starts it, the graph in miniature. Click the card to open the workflow. */
export function WorkflowHoverCard({ row, icon, disabled, onOpen, children }: {
  row: AutomationSummaryDto;
  icon: ReactNode;
  disabled?: boolean;
  onOpen: () => void;
  children: ReactNode;
}) {
  return (
    <EditorTabHoverCardShell placement="right" disabled={disabled} cardHeight={300} card={<CardBody row={row} icon={icon} onOpen={onOpen} />}>
      {children}
    </EditorTabHoverCardShell>
  );
}
