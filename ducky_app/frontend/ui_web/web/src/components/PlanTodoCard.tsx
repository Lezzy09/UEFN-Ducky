import { PlanOwnerChips } from "./PlanOwnerChips";
import { useMemo, useState, type CSSProperties } from "react";
import type { ChatPlan, PlanNode, PlanProgress, PlanTodoStatus } from "../types/panel";
import { progressForPlan } from "../utils/planOutlineNav";
import { isPlanFinished, isPlanPaused, nodeKind } from "../utils/planLock";

export interface PlanTodoCardProps {
  plan: ChatPlan;
  progress?: PlanProgress | null;
  onOpenPlan?: () => void;
  compact?: boolean;
  /** Templates: no N/M progress chrome. */
  hideProgress?: boolean;
  /** Hide the title row when the parent already shows the plan title. */
  hideTitlebar?: boolean;
  /** Chat popup: parent owns open/close. No title row and no step-list collapse. */
  embedded?: boolean;
  /** Click an outline row — drill into subplan or scroll to that step. */
  onSelectNode?: (node: PlanNode) => void;
  /** Highlight this node id briefly / as selected. */
  highlightNodeId?: string | null;
}

type OutlineRow = { label: string; node: PlanNode; depth: number; owner?: string };

function flattenOutline(nodes: PlanNode[] | undefined, prefix = "", inheritedOwner?: string): OutlineRow[] {
  const out: OutlineRow[] = [];
  (nodes || []).forEach((node, i) => {
    const label = prefix ? `${prefix}.${i + 1}` : `${i + 1}`;
    const depth = prefix ? prefix.split(".").length : 0;
    const owner = node.assignee || node.assignee_inferred || inheritedOwner;
    out.push({ label, node, depth, owner });
    if (node.children?.length) out.push(...flattenOutline(node.children, label, owner));
  });
  return out;
}

function nodesFromPlan(plan: ChatPlan): PlanNode[] {
  if (plan.nodes?.length) return plan.nodes;
  return (plan.todos || []).map((t) => ({
    id: t.id,
    content: t.content,
    status: t.status,
    children: [],
  }));
}

function countProgress(plan: ChatPlan, progress?: PlanProgress | null): { done: number; total: number } {
  const counts = progress ?? progressForPlan(plan);
  return { done: counts.completed, total: counts.total };
}

const isDone = (status: string) => status === "completed" || status === "cancelled";
// ponytail: a member's BLOCKED line lives in its step notes; read it from there until nodes carry a blocked field.
const BLOCKED = /^\s*BLOCKED:\s*(.+)$/m;

/** Outline labels of the unfinished `after` steps, per pending node that waits on them. */
function handOffWaits(rows: OutlineRow[]): Map<string, string[]> {
  const byId = new Map(rows.map((row) => [row.node.id, row]));
  const waits = new Map<string, string[]>();
  for (const { node } of rows) {
    if (node.status !== "pending") continue;
    const open = ((node as PlanNode & { after?: string[] }).after || [])
      .map((id) => byId.get(id))
      .filter((row): row is OutlineRow => Boolean(row) && !isDone(row!.node.status))
      .map((row) => row.label);
    if (open.length) waits.set(node.id, open);
  }
  return waits;
}

export type PlanStatusPart = { text: string; title?: string };

/** One plain line: paused, who is working, waiting on hand-offs or blocked, or done. */
export function planStatusLine(plan: ChatPlan, progress?: PlanProgress | null): PlanStatusPart[] {
  const rows = flattenOutline(nodesFromPlan(plan));
  const { done, total } = countProgress(plan, progress);
  const count = { text: `${done}/${total}` };
  if ((total > 0 && done >= total) || isPlanFinished(plan)) return [{ text: "Done" }, count];
  if (isPlanPaused(plan)) {
    const sections = rows.filter((row) => nodeKind(row.node) === "subplan").length;
    const started = rows.some((row) => row.node.status !== "pending");
    return [{ text: "Paused" }, count, { text: `${sections} sections${started ? "" : ", nobody started"}` }, { text: "press Play" }];
  }
  const byLabel = new Map(rows.map((row) => [row.label, row]));
  const active = rows.filter((row) => row.node.status === "in_progress");
  const blocked = active.flatMap((row) => {
    const why = BLOCKED.exec(row.node.body_markdown || "")?.[1]?.trim();
    if (!why) return [];
    // A blocked step is named by its section ("Agent host"), a blocked section by itself.
    const parent = row.node.children?.length ? row : byLabel.get(row.label.split(".").slice(0, -1).join(".")) || row;
    return [`${parent.node.content} — ${why}`];
  });
  const working = active.filter((row) => !row.node.children?.length).length - blocked.length;
  const waits = handOffWaits(rows);
  const parts: PlanStatusPart[] = [{ text: `${Math.max(0, working)} working` }];
  if (waits.size) {
    const title = rows.filter((row) => waits.has(row.node.id))
      .map((row) => `${row.label} ${row.node.content} waits for ${waits.get(row.node.id)!.join(", ")}`).join("\n");
    parts.push({ text: `${waits.size} waiting on hand-offs`, title });
  }
  if (blocked.length) parts.push({ text: `${blocked.length} blocked: ${blocked.join("; ")}` });
  parts.push(count);
  return parts;
}

export function PlanStatusLine({ plan, progress }: { plan: ChatPlan; progress?: PlanProgress | null }) {
  const parts = useMemo(() => planStatusLine(plan, progress), [plan, progress]);
  return (
    <div className="plan-status-line" role="status">
      {parts.map((part, i) => (
        <span key={i} title={part.title}>{i ? " · " : ""}{part.text}</span>
      ))}
    </div>
  );
}

function TodoRow({
  label,
  content,
  status,
  depth,
  nodeId,
  kind,
  clickable,
  highlighted,
  waitsFor,
  onSelect,
}: {
  label: string;
  content: string;
  status: PlanTodoStatus | string;
  depth: number;
  nodeId: string;
  kind: "step" | "subplan";
  clickable?: boolean;
  highlighted?: boolean;
  /** Outline labels of the hand-offs this row waits for. */
  waitsFor?: string[];
  onSelect?: () => void;
}) {
  const done = status === "completed" || status === "cancelled";
  const active = status === "in_progress";
  const className = `plan-todo-row${done ? " is-done" : ""}${active ? " is-active" : ""}${
    clickable ? " is-clickable" : ""
  }${highlighted ? " is-highlight" : ""}${kind === "subplan" ? " is-subplan" : " is-step"}`;
  const check = (
    <span className="plan-todo-check" aria-hidden>
      {done ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <circle cx="12" cy="12" r="10" />
          <path d="M8 12l2.5 2.5L16 9" />
        </svg>
      ) : active ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="3" fill="currentColor" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
        </svg>
      )}
    </span>
  );
  const body = (
    <>
      <span className="plan-todo-outline-n" aria-hidden>
        {label}
      </span>
      <span className={`plan-todo-kind${kind === "subplan" ? " plan-todo-kind--subplan" : ""}`}>
        {kind === "subplan" ? "Subplan" : "Step"}
      </span>
      {check}
      <span className="plan-todo-text">{content}</span>
      {waitsFor?.length ? (
        <span className="plan-todo-waits" style={{ opacity: 0.6, marginLeft: 6 }}>
          waits for {waitsFor.join(", ")}
        </span>
      ) : null}
    </>
  );
  // Plans nest without limit: the indent follows the real depth (CSS --plan-depth).
  const depthClass = depth ? " plan-todo-row--nested" : "";
  const depthStyle = depth ? ({ "--plan-depth": depth } as CSSProperties) : undefined;
  if (clickable && onSelect) {
    return (
      <button
        type="button"
        className={`${className}${depthClass}`}
        style={depthStyle}
        data-plan-node-id={nodeId}
        data-status={status}
        onClick={onSelect}
        title={kind === "subplan" ? "Open this subplan" : "Open this step"}
      >
        {body}
      </button>
    );
  }
  return (
    <div className={`${className}${depthClass}`} style={depthStyle} data-plan-node-id={nodeId} data-status={status}>
      {body}
    </div>
  );
}

export function PlanTodoCard({
  plan,
  progress,
  onOpenPlan,
  compact = false,
  hideProgress = false,
  hideTitlebar = false,
  embedded = false,
  onSelectNode,
  highlightNodeId = null,
}: PlanTodoCardProps) {
  const outline = useMemo(() => flattenOutline(nodesFromPlan(plan)), [plan]);
  const waits = useMemo(() => handOffWaits(outline), [outline]);
  const { done, total } = useMemo(() => countProgress(plan, progress), [plan, progress]);
  const [expanded, setExpanded] = useState(true);
  const allDone = total > 0 && done >= total;
  const isTemplate = hideProgress || plan.kind === "template";

  return (
    <div
      className={`plan-todo-card${compact ? " plan-todo-card--compact" : ""}${
        hideTitlebar ? " plan-todo-card--aside" : ""
      }${embedded ? " plan-todo-card--embedded" : ""}`}
    >
      {!hideTitlebar && !embedded ? (
        <div className="plan-todo-card-titlebar">
          <button type="button" className="plan-todo-card-title-btn" onClick={onOpenPlan} title="Open plan tab">
            {plan.title || "Plan"}
          </button>
        </div>
      ) : null}
      {!hideTitlebar && !embedded && !isTemplate ? <PlanStatusLine plan={plan} progress={progress} /> : null}
      {embedded ? null : (
        <button
          type="button"
          className="plan-todo-card-header"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <span className="plan-todo-card-header-label">
            {isTemplate
              ? `${total} steps`
              : allDone
                ? `${done} of ${total} steps completed`
                : `${done} of ${total} steps`}
          </span>
          <span className={`plan-todo-card-chevron${expanded ? " is-expanded" : ""}`} aria-hidden>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>
      )}
      {embedded || expanded ? (
        <div className="plan-todo-card-body">
          {outline.map(({ label, node, depth, owner }) => (
            <div key={node.id}>
            <TodoRow
              label={label}
              content={node.content}
              status={node.status}
              depth={depth}
              nodeId={node.id}
              kind={nodeKind(node)}
              clickable={Boolean(onSelectNode)}
              highlighted={highlightNodeId === node.id}
              waitsFor={waits.get(node.id)}
              onSelect={onSelectNode ? () => onSelectNode(node) : undefined}
            />
            {!isTemplate && owner && (node.assignee || node.assignee_inferred || node.status === "in_progress") ? (
              <PlanOwnerChips ownerId={owner} activeOnly={!(node.assignee || node.assignee_inferred)} nodeId={node.id} />
            ) : null}
            </div>
          ))}
          {!outline.length ? <div className="plan-todo-empty">No steps yet.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

/** Compat export for callers that still think in flat todos. */
export type { PlanTodoStatus };
