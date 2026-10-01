/**
 * Show me: take the user to one part of the app, highlight it and explain it in a popup
 * above it. Only the popup's close button ends it — no Esc, no click elsewhere, no timer,
 * no route change — so the user stays on that UI until they close it.
 *
 * The AI plays it with `ducky_ui_show`; the chat card's Show me button plays it again.
 */
import { requestFocusGraph } from "../hooks/graphActivity";
import { openPanelRoute } from "../navigation/openPanelRoute";
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import { isTargetSpec, revealTarget, runUiAction, targetKey, waitForTarget, type TargetSpec } from "../ui-targets/resolve";

export interface ShowMeRequest {
  /** One target, or several shown as one highlight (a group of nodes). */
  target: TargetSpec | TargetSpec[];
  title: string;
  body: string;
  /** Open this workflow first (targets like `workflows.node.<id>` are then selected). */
  workflow_id?: string;
  /** A panel route to open first (`settings.store`, `workflows`, `files`…). */
  navigate?: string;
  item_id?: string;
  /** A UI action to run first (`workflows.add_menu`, `files.reveal`…). */
  action?: { id: string; args?: Record<string, unknown> };
}

export type ShowMePhase = "going" | "shown" | "missing";

export interface ShowMeState {
  request: ShowMeRequest | null;
  phase: ShowMePhase;
  /** Bumps on every play, so the layer restarts its measuring. */
  key: number;
}

export interface ShowMeResult {
  ok: boolean;
  shown: boolean;
  missing: boolean;
  target: string;
  closed?: boolean;
  error?: string;
}

type Listener = (state: ShowMeState) => void;

const listeners = new Set<Listener>();
let state: ShowMeState = { request: null, phase: "going", key: 0 };
let closedWaiters: Array<() => void> = [];

function emit(): void {
  for (const l of listeners) {
    try {
      l(state);
    } catch {
      /* ignore subscriber errors */
    }
  }
}

export function subscribeShowMe(listener: Listener): () => void {
  listeners.add(listener);
  listener(state);
  return () => listeners.delete(listener);
}

export function getShowMeState(): ShowMeState {
  return state;
}

export function targetsOf(request: Pick<ShowMeRequest, "target">): TargetSpec[] {
  const raw = Array.isArray(request.target) ? request.target : [request.target];
  return raw.filter(isTargetSpec);
}

/** Read a request from tool arguments (the AI's call, or a chat card replaying it). */
export function parseShowMeRequest(raw: unknown): ShowMeRequest | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const a = raw as Record<string, unknown>;
  const target = Array.isArray(a.target) ? a.target.filter(isTargetSpec) : isTargetSpec(a.target) ? a.target : null;
  if (!target || (Array.isArray(target) && !target.length)) return null;
  const title = String(a.title || "").trim();
  const body = String(a.body || "").trim();
  if (!title && !body) return null;
  const action = a.action && typeof a.action === "object" && !Array.isArray(a.action) && (a.action as { id?: unknown }).id
    ? { id: String((a.action as { id: unknown }).id), args: ((a.action as { args?: unknown }).args as Record<string, unknown>) || {} }
    : undefined;
  return {
    target: target as TargetSpec | TargetSpec[],
    title: title || body.slice(0, 60),
    body,
    workflow_id: String(a.workflow_id || "").trim() || undefined,
    navigate: String(a.navigate || "").trim() || undefined,
    item_id: String(a.item_id || "").trim() || undefined,
    action,
  };
}

/** Workflow nodes named by the targets (`workflows.node.<id>`), to select them. */
function workflowNodes(targets: TargetSpec[]): string[] {
  return targets
    .map((t) => (typeof t === "string" ? t : t.id || ""))
    .filter((id) => id.startsWith("workflows.node."))
    .map((id) => id.slice("workflows.node.".length));
}

const wait = (ms: number) => new Promise<void>((r) => globalThis.setTimeout(r, ms));
let findTimeoutMs = 5000;

/** Go there, highlight, explain. Resolves once it is on screen (or can't be found). */
export async function playShowMe(request: ShowMeRequest): Promise<ShowMeResult> {
  const targets = targetsOf(request);
  const key = targets.map(targetKey).join(", ");
  if (!targets.length) return { ok: false, shown: false, missing: true, target: key, error: "no target" };
  // A new Show me replaces the one on screen (its waiter hears it closed).
  if (state.request) settleClosed();
  state = { request, phase: "going", key: state.key + 1 };
  const myKey = state.key;
  emit();
  try {
    if (request.navigate) openPanelRoute(request.navigate, request.item_id || "");
    if (request.workflow_id) {
      const nodes = workflowNodes(targets);
      requestOpenWorkflowsTab();
      requestFocusGraph(request.workflow_id, nodes.length ? { nodes, select: true } : {});
    }
    if (request.navigate || request.workflow_id) await wait(250);
    if (request.action?.id) {
      const done = await runUiAction(request.action.id, request.action.args || {});
      if (!done.ok) console.warn("[show-me] action failed", done.error);
      await wait(150);
    }
    const found = await Promise.all(targets.map((t) => waitForTarget(t, findTimeoutMs)));
    if (state.key !== myKey) return { ok: true, shown: false, missing: false, target: key };
    if (found.some(Boolean)) {
      await revealTarget(targets[found.findIndex(Boolean)]);
      await wait(request.workflow_id ? 450 : 200);  // let a canvas glide land before the ring settles
    }
    if (state.key !== myKey) return { ok: true, shown: false, missing: false, target: key };
    const missing = !found.some(Boolean);
    state = { ...state, phase: missing ? "missing" : "shown" };
    emit();
    return { ok: true, shown: !missing, missing, target: key };
  } catch (err) {
    if (state.key === myKey) {
      state = { ...state, phase: "missing" };
      emit();
    }
    return { ok: false, shown: false, missing: true, target: key, error: err instanceof Error ? err.message : String(err) };
  }
}

function settleClosed(): void {
  const waiters = closedWaiters;
  closedWaiters = [];
  for (const w of waiters) w();
}

/** The close button — the only way out. */
export function closeShowMe(): void {
  if (!state.request) return;
  state = { request: null, phase: "going", key: state.key + 1 };
  emit();
  settleClosed();
}

/** Resolves when the Show me on screen now is closed (or replaced). */
export function whenShowMeClosed(): Promise<void> {
  if (!state.request) return Promise.resolve();
  return new Promise((resolve) => closedWaiters.push(resolve));
}

/** Test helper. */
export function _resetShowMeForTests(findMs = 5000): void {
  findTimeoutMs = findMs;
  listeners.clear();
  closedWaiters = [];
  state = { request: null, phase: "going", key: 0 };
}
