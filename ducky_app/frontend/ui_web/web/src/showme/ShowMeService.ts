/**
 * Show me: take the user to one part of the app, highlight it and explain it in a popup
 * above it. Only the popup's close button ends it — no Esc, no click elsewhere, no timer,
 * no route change — so the user stays on that UI until they close it.
 *
 * It can have several steps: Back / Next walk them in the same popup (a step may move on
 * when the user clicks the highlighted thing), and the last one has a Close button.
 *
 * The AI plays it with `ducky_ui_show`; the chat card's Show me button plays it again.
 */
import { requestFocusGraph } from "../hooks/graphActivity";
import { openPanelRoute } from "../navigation/openPanelRoute";
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import { isTargetSpec, revealTarget, runUiAction, targetKey, waitForTarget, type TargetSpec } from "../ui-targets/resolve";

export interface ShowMeStep {
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
  /** Move to the next step when the user clicks the highlighted thing. */
  click?: boolean;
}

/** One step, or several in `steps` (the top-level fields are then the first step). */
export interface ShowMeRequest extends ShowMeStep {
  steps?: ShowMeStep[];
}

export type ShowMePhase = "going" | "shown" | "missing";

export interface ShowMeState {
  /** The step on screen now (null when closed). */
  request: ShowMeStep | null;
  phase: ShowMePhase;
  /** Bumps on every step played, so the layer restarts its measuring. */
  key: number;
  /** Which step of how many (0-based; total 1 for a single Show me). */
  index: number;
  total: number;
}

export interface ShowMeResult {
  ok: boolean;
  shown: boolean;
  missing: boolean;
  target: string;
  steps?: number;
  closed?: boolean;
  error?: string;
}

type Listener = (state: ShowMeState) => void;

const listeners = new Set<Listener>();
const CLOSED: ShowMeState = { request: null, phase: "going", key: 0, index: 0, total: 0 };
let state: ShowMeState = { ...CLOSED };
let steps: ShowMeStep[] = [];
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

export function targetsOf(request: Pick<ShowMeStep, "target">): TargetSpec[] {
  const raw = Array.isArray(request.target) ? request.target : [request.target];
  return raw.filter(isTargetSpec);
}

function parseStep(raw: unknown): ShowMeStep | null {
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
    ...(a.click === true ? { click: true } : {}),
  };
}

/** Read a request from tool arguments (the AI's call, or a chat card replaying it). */
export function parseShowMeRequest(raw: unknown): ShowMeRequest | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const a = raw as Record<string, unknown>;
  const list = Array.isArray(a.steps) ? a.steps.map(parseStep).filter((s): s is ShowMeStep => !!s) : [];
  const first = parseStep(a) ?? list[0] ?? null;
  if (!first) return null;
  // With steps, the top-level fields (when given) are the first step.
  const all = list.length ? (parseStep(a) ? [first, ...list] : list) : [];
  return all.length > 1 ? { ...first, steps: all } : first;
}

/** The steps a request plays (one for a single Show me). */
export function stepsOf(request: ShowMeRequest): ShowMeStep[] {
  return request.steps?.length ? request.steps : [request];
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

/** Go there, highlight, explain. Resolves once the first step is on screen (or can't be found). */
export async function playShowMe(request: ShowMeRequest): Promise<ShowMeResult> {
  const list = stepsOf(request);
  if (!targetsOf(list[0]).length) return { ok: false, shown: false, missing: true, target: "", error: "no target" };
  // A new Show me replaces the one on screen (its waiter hears it closed).
  if (state.request) settleClosed();
  steps = list;
  const out = await playStep(0);
  return { ...out, steps: list.length };
}

async function playStep(index: number): Promise<ShowMeResult> {
  const step = steps[index];
  const targets = step ? targetsOf(step) : [];
  const key = targets.map(targetKey).join(", ");
  if (!step || !targets.length) return { ok: false, shown: false, missing: true, target: key, error: "no target" };
  state = { request: step, phase: "going", key: state.key + 1, index, total: steps.length };
  const myKey = state.key;
  emit();
  try {
    if (step.navigate) openPanelRoute(step.navigate, step.item_id || "");
    if (step.workflow_id) {
      const nodes = workflowNodes(targets);
      requestOpenWorkflowsTab();
      requestFocusGraph(step.workflow_id, nodes.length ? { nodes, select: true } : {});
    }
    if (step.navigate || step.workflow_id) await wait(250);
    if (step.action?.id) {
      const done = await runUiAction(step.action.id, step.action.args || {});
      if (!done.ok) console.warn("[show-me] action failed", done.error);
      await wait(150);
    }
    const found = await Promise.all(targets.map((t) => waitForTarget(t, findTimeoutMs)));
    if (state.key !== myKey) return { ok: true, shown: false, missing: false, target: key };
    if (found.some(Boolean)) {
      await revealTarget(targets[found.findIndex(Boolean)]);
      await wait(step.workflow_id ? 450 : 200);  // let a canvas glide land before the ring settles
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

/** Next step (nothing on the last one: Close ends it). */
export function nextShowMe(): void {
  if (state.request && state.index < steps.length - 1) void playStep(state.index + 1);
}

export function backShowMe(): void {
  if (state.request && state.index > 0) void playStep(state.index - 1);
}

function settleClosed(): void {
  const waiters = closedWaiters;
  closedWaiters = [];
  for (const w of waiters) w();
}

/** The close button — the only way out. */
export function closeShowMe(): void {
  if (!state.request) return;
  steps = [];
  state = { ...CLOSED, key: state.key + 1 };
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
  steps = [];
  state = { ...CLOSED };
}
