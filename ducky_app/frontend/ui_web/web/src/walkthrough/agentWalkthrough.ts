/**
 * Ephemeral agent-authored tours — same coachmark UI as product walkthroughs,
 * not persisted to walkthrough_completed.
 */
import { openPanelRoute } from "../navigation/openPanelRoute";
import { isTargetSpec, runUiAction, targetKey, type TargetSpec } from "../ui-targets/resolve";
import type { WalkthroughAdvance, WalkthroughSpotlightMode, WalkthroughStep } from "./types";
import {
  getWalkthroughState,
  registerTour,
  setWalkthroughFinishHook,
  skipTour,
  startTour,
  unregisterTour,
} from "./WalkthroughService";

export const AGENT_TOUR_ID = "agent.ephemeral";

function ensureFinishHook(): void {
  setWalkthroughFinishHook((tourId, reason) => {
    if (tourId !== AGENT_TOUR_ID) return;
    settleAgentWalkthrough(reason);
  });
}

export type AgentWalkthroughStepInput = {
  /** An id, or `{role, name, within}` / `{text}` for things with no id. */
  target: TargetSpec;
  title?: string;
  body?: string;
  /** Alias for body. */
  label?: string;
  advance?: WalkthroughAdvance | string;
  mode?: WalkthroughSpotlightMode | string;
  /** Optional route to open before the step (same ids as ducky_ui_navigate). */
  navigate?: string;
  item_id?: string;
  /** Optional UI action to run before the step (`workflows.open {id}`, `workflows.add_menu`). */
  action?: { id: string; args?: Record<string, unknown> };
};

function wait(ms: number): Promise<void> {
  return new Promise((r) => globalThis.setTimeout(r, ms));
}

type AgentFinish = { ok: true; completed: boolean; skipped: boolean; tour_id: string };

let pendingResolve: ((r: AgentFinish) => void) | null = null;

/** Called from WalkthroughService when an agent tour ends. */
export function settleAgentWalkthrough(reason: "complete" | "skip"): void {
  const resolve = pendingResolve;
  pendingResolve = null;
  if (resolve) {
    resolve({
      ok: true,
      completed: reason === "complete",
      skipped: reason === "skip",
      tour_id: AGENT_TOUR_ID,
    });
  }
}

export function parseAgentWalkthroughSteps(raw: unknown): WalkthroughStep[] {
  if (!Array.isArray(raw)) return [];
  const out: WalkthroughStep[] = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") continue;
    const s = row as AgentWalkthroughStepInput & { spotlight?: string };
    const raw = s.target ?? s.spotlight;
    if (!isTargetSpec(raw)) continue;
    const spec = typeof raw === "string" ? undefined : raw;
    const target = typeof raw === "string" ? raw.trim() : targetKey(raw);
    const body = String(s.body || s.label || "").trim();
    const title = String(s.title || "").trim() || body.slice(0, 48) || target;
    const advance: WalkthroughAdvance = s.advance === "require_click" ? "require_click" : "next";
    const mode: WalkthroughSpotlightMode = s.mode === "circle" ? "circle" : "rect";
    const navigate = String(s.navigate || "").trim();
    const itemId = String(s.item_id || "").trim();
    const action = s.action && typeof s.action === "object" && s.action.id ? { id: String(s.action.id), args: s.action.args || {} } : null;
    out.push({
      target,
      ...(spec ? { spec } : {}),
      title,
      body: body || title,
      advance,
      mode,
      onEnter: navigate || action
        ? async () => {
            if (navigate) {
              openPanelRoute(navigate, itemId);
              await wait(300);
            }
            if (action) {
              await runUiAction(action.id, action.args);
              await wait(250);
            }
          }
        : undefined,
    });
  }
  return out;
}

/**
 * Register + start an ephemeral coachmark tour. Resolves when the user finishes
 * or skips. Replaces any in-flight agent tour.
 */
export async function runAgentWalkthrough(rawSteps: unknown): Promise<Record<string, unknown>> {
  ensureFinishHook();
  const steps = parseAgentWalkthroughSteps(rawSteps);
  if (!steps.length) {
    return { error: "steps must be a non-empty list of {target, title, body}" };
  }

  if (pendingResolve) {
    settleAgentWalkthrough("skip");
  }
  if (getWalkthroughState().tourId === AGENT_TOUR_ID) {
    await skipTour();
  }

  unregisterTour(AGENT_TOUR_ID);
  registerTour({
    id: AGENT_TOUR_ID,
    title: "Guided tour",
    autoStart: "never",
    persist: false,
    steps,
  });

  return new Promise<Record<string, unknown>>((resolve) => {
    pendingResolve = (r) => resolve(r);
    void startTour(AGENT_TOUR_ID, { force: true }).then((ok) => {
      if (!ok) {
        pendingResolve = null;
        resolve({ error: "failed to start walkthrough" });
      }
    });
  });
}
