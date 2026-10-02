import { useSyncExternalStore } from "react";

import type { AgentEvent, PanelPushEvent } from "../types/panel";
import { subscribeAgentEvents } from "./useAgentEventBus";
import { subscribePanelPush } from "./usePanelPushBus";

/**
 * The workflow a chat's ducky is running, step by step, for the card above the plan.
 *
 * The runner's `workflow_run` start event names the calling chat, the workflow and its
 * happy-path steps; `workflow_step` events then say which step runs and how it ended.
 * Kept at module level so it follows the run while the chat's tab is not mounted.
 * The events can reach either UI bus, so applying one twice changes nothing.
 */

export type WorkflowStepState = "pending" | "running" | "ok" | "error" | "stopped";

export interface ChatWorkflowStep {
  node: string;
  label: string;
  type: string;
  state: WorkflowStepState;
  error?: string;
  /** Ran but is not on the happy path (a failure report, a fix step). */
  extra?: boolean;
}

export interface ChatWorkflowRun {
  workflowId: string;
  run: string;
  name: string;
  state: "running" | "done" | "error" | "stopped";
  error?: string;
  steps: ChatWorkflowStep[];
  /** Node id of the step running now ("" when none). */
  current: string;
}

type WorkflowEvent = Pick<PanelPushEvent, "type" | "id" | "run" | "node" | "state" | "error" | "conv" | "name" | "plan" | "label">;

const byChat = new Map<string, ChatWorkflowRun>();
const runToChat = new Map<string, string>();
const listeners = new Set<() => void>();
let installed = false;

function emit(): void {
  for (const listener of listeners) listener();
}

function stepState(raw: string | undefined): WorkflowStepState {
  return raw === "ok" || raw === "error" || raw === "stopped" ? raw : "running";
}

export function applyWorkflowEvent(event: WorkflowEvent): void {
  const run = String(event.run || "");
  if (!run) return;
  if (event.type === "workflow_run" && event.state === "started") {
    const chat = String(event.conv || "");
    if (!chat || byChat.get(chat)?.run === run) return;
    runToChat.set(run, chat);
    byChat.set(chat, {
      workflowId: String(event.id || ""),
      run,
      name: String(event.name || "Workflow"),
      state: "running",
      steps: (event.plan || []).map((p) => ({ node: p.node, label: p.label || p.node, type: p.type || "", state: "pending" })),
      current: "",
    });
    emit();
    return;
  }
  const chat = runToChat.get(run);
  const current = chat ? byChat.get(chat) : undefined;
  if (!chat || !current || current.run !== run) return;

  if (event.type === "workflow_run") {
    if (current.state !== "running") return;
    const state = event.state === "stopped" ? "stopped" : event.state === "error" ? "error" : "done";
    const steps = current.steps.map((s) => (s.state === "running" ? { ...s, state: state === "done" ? "ok" : state } as ChatWorkflowStep : s));
    byChat.set(chat, { ...current, state, error: event.error || undefined, steps, current: "" });
    emit();
    return;
  }
  if (event.type !== "workflow_step") return;
  const node = String(event.node || "");
  if (!node) return;
  const state = stepState(event.state);
  const index = current.steps.findIndex((s) => s.node === node);
  const prev = index >= 0 ? current.steps[index] : undefined;
  if (prev && prev.state === state && (prev.error || "") === (event.error || "")) return;
  const next: ChatWorkflowStep = prev
    ? { ...prev, state, error: event.error || undefined }
    : { node, label: event.label || node, type: "", state, error: event.error || undefined, extra: true };
  const steps = index >= 0 ? current.steps.map((s, i) => (i === index ? next : s)) : [...current.steps, next];
  byChat.set(chat, {
    ...current,
    steps,
    current: state === "running" ? node : current.current === node ? "" : current.current,
  });
  emit();
}

function onEvent(event: AgentEvent | PanelPushEvent): void {
  const type = String(event.type || "");
  if (type === "workflow_run" || type === "workflow_step") applyWorkflowEvent(event as WorkflowEvent);
}

function install(): void {
  if (installed) return;
  installed = true;
  subscribePanelPush(onEvent);
  subscribeAgentEvents(onEvent);
}

function subscribe(listener: () => void): () => void {
  install();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Hide a finished run's card. */
export function dismissWorkflowRun(chatId: string): void {
  if (byChat.delete(chatId)) emit();
}

export function useChatWorkflowRun(chatId: string): ChatWorkflowRun | null {
  return useSyncExternalStore(
    subscribe,
    () => byChat.get(chatId) ?? null,
    () => null,
  );
}

export function resetWorkflowRunsForTests(): void {
  byChat.clear();
  runToChat.clear();
}
