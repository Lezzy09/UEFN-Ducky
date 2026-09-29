import type { AutomationSummaryDto, PanelPushEvent } from "../types/panel";
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import {
  dismissBackgroundJob,
  upsertBackgroundJob,
  type BackgroundJob,
} from "./backgroundActivity";

export const GRAPH_JOB_PREFIX = "graph:";
export const GRAPH_RUN_PREFIX = "graph-run:";

export function graphJobId(workflowId: string): string {
  return `${GRAPH_JOB_PREFIX}${workflowId}`;
}

export function workflowIdFromJobId(jobId: string): string {
  const id = String(jobId || "");
  if (id.startsWith(GRAPH_RUN_PREFIX)) {
    const rest = id.slice(GRAPH_RUN_PREFIX.length);
    const cut = rest.lastIndexOf(":");
    return cut > 0 ? rest.slice(0, cut) : rest;
  }
  if (id.startsWith(GRAPH_JOB_PREFIX)) return id.slice(GRAPH_JOB_PREFIX.length);
  return "";
}

let pendingFocus: string | null = null;

export function requestFocusGraph(id: string): void {
  const wid = id.trim();
  if (!wid) return;
  pendingFocus = wid;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("ducky:focus-graph", { detail: { id: wid } }));
  }
}

/** Chat saved or deleted a workflow — open the editor and show the change. */
export function applyGraphFocusPush(event: PanelPushEvent): void {
  if (event.type !== "graph_focus") return;
  const id = String(event.id || "").trim();
  if (!id) return;
  requestOpenWorkflowsTab();
  if (event.action === "deleted") {
    if (pendingFocus === id) pendingFocus = null;
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("ducky:graph-deleted", { detail: { id } }));
    }
    return;
  }
  requestFocusGraph(id);
}

export function takePendingGraphFocus(): string {
  const id = pendingFocus || "";
  pendingFocus = null;
  return id;
}

export function applyBackgroundJobPush(event: PanelPushEvent | (Partial<BackgroundJob> & { id?: string })): void {
  const id = String(event.id || "").trim();
  if (!id) return;
  upsertBackgroundJob({
    id,
    source: event.source,
    title: "title" in event ? event.title : undefined,
    detail: event.detail,
    percent: "percent" in event ? event.percent : undefined,
    phase: event.phase,
    cancelable: "cancelable" in event ? event.cancelable : undefined,
  });
}

export function syncReadyGraphJobs(
  _rows: Array<Pick<AutomationSummaryDto, "id" | "name" | "enabled" | "node_count">>,
  current: BackgroundJob[],
): void {
  for (const job of current) {
    if (job.id.startsWith(GRAPH_JOB_PREFIX) && job.phase === "ready") {
      dismissBackgroundJob(job.id);
    }
  }
}
