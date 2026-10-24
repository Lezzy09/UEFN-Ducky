import { useEffect, useState } from "react";
import { subscribeAgentEvents } from "../hooks/useAgentEventBus";
import { getApi } from "../hooks/usePanelApi";
import type { AgentEvent } from "../types/panel";

export type TerminalRunner = "mcp" | "user";

export interface TerminalBusyStatus {
  running: boolean;
  runner: TerminalRunner | null;
}

/** Busy pushes for many shells within this window become one terminal_busy_many call. */
const COALESCE_MS = 1000;

function deriveRunner(busy?: boolean, running?: boolean): TerminalRunner | null {
  if (!running) return null;
  return busy ? "mcp" : "user";
}

/**
 * One store for every component that shows terminal activity (the header list and each
 * editor group's tab strip). A session is asked about once when first watched, then only
 * after Terminal pushes `terminal_busy` for it (a command started or ended); nothing polls.
 */
interface Watcher {
  ids: string[];
  notify: () => void;
}

const watchers = new Set<Watcher>();
const statuses = new Map<string, TerminalBusyStatus>();
const NOT_RUNNING: TerminalBusyStatus = { running: false, runner: null };
let unsubscribe: (() => void) | null = null;
let inFlight = false;
/** Sessions to ask about on the next call (pushed, or new while a call was out). */
const pending = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;

function watchedIds(): Set<string> {
  return new Set([...watchers].flatMap((watcher) => watcher.ids));
}

function notifyAll(): void {
  for (const watcher of watchers) watcher.notify();
}

async function ask(ids: string[]): Promise<void> {
  if (inFlight) {
    for (const id of ids) pending.add(id);
    return;
  }
  const api = getApi();
  if (!api || ids.length === 0) return;
  inFlight = true;
  let states: Record<string, { ok: boolean; busy?: boolean; running?: boolean }> = {};
  try {
    const result = await api.terminal_busy_many(ids);
    states = result?.states ?? {};
  } catch {
    // Same as a session the backend no longer knows: shown as not running.
  } finally {
    inFlight = false;
  }
  const watched = watchedIds();
  let changed = false;
  for (const id of ids) {
    if (!watched.has(id)) continue; // its tab closed while the call was out
    const state = states[id];
    const running = !!state?.ok && !!state.running;
    const runner = running ? deriveRunner(state?.busy, running) : null;
    const prev = statuses.get(id);
    if (prev && prev.running === running && prev.runner === runner) continue;
    statuses.set(id, running ? { running, runner } : NOT_RUNNING);
    changed = true;
  }
  if (changed) notifyAll();
  if (pending.size > 0 && timer === null) flushSoon();
}

function flushSoon(): void {
  if (timer !== null) return;
  timer = setTimeout(() => {
    timer = null;
    const watched = watchedIds();
    const ids = [...pending].filter((id) => watched.has(id));
    pending.clear();
    void ask(ids);
  }, COALESCE_MS);
}

function onPush(event: AgentEvent): void {
  const id = String((event as { session_id?: unknown }).session_id || "");
  if (!id || !watchedIds().has(id)) return;
  if (event.type === "terminal_close" || (event.type as string) === "terminal_exit") {
    if (statuses.get(id) === NOT_RUNNING) return;
    statuses.set(id, NOT_RUNNING);
    notifyAll();
    return;
  }
  if ((event.type as string) !== "terminal_busy") return;
  pending.add(id);
  flushSoon();
}

function watch(watcher: Watcher): () => void {
  watchers.add(watcher);
  void ask(watcher.ids.filter((id) => !statuses.has(id)));
  if (!unsubscribe) unsubscribe = subscribeAgentEvents(onPush);
  return () => {
    watchers.delete(watcher);
    const watched = watchedIds();
    for (const id of [...statuses.keys()]) if (!watched.has(id)) statuses.delete(id);
    if (watchers.size === 0) {
      unsubscribe?.();
      unsubscribe = null;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending.clear();
    }
  };
}

function pick(ids: readonly string[]): Map<string, TerminalBusyStatus> {
  const next = new Map<string, TerminalBusyStatus>();
  for (const id of ids) {
    const status = statuses.get(id);
    if (status) next.set(id, status);
  }
  return next;
}

function sameStatuses(prev: Map<string, TerminalBusyStatus>, next: Map<string, TerminalBusyStatus>): boolean {
  if (prev.size !== next.size) return false;
  for (const [id, status] of next) if (prev.get(id) !== status) return false;
  return true;
}

/**
 * Busy state per session. Parked sessions (closed tabs whose shell lives on) are pushed
 * like open ones now, so the second argument is kept only for existing callers.
 */
export function useTerminalBusyStatuses(
  sessionIds: string[],
  parkedSessionIds: readonly string[] = [],
): Map<string, TerminalBusyStatus> {
  const [statusMap, setStatusMap] = useState<Map<string, TerminalBusyStatus>>(() => new Map());
  const idsKey = [...sessionIds, ...parkedSessionIds].filter(Boolean).sort().join("\0");

  useEffect(() => {
    const ids = idsKey ? [...new Set(idsKey.split("\0"))] : [];
    // Only a value that changed re-renders: an idle poll used to re-render the tab strip
    // and, through the header actions, the whole header every 2 s.
    const update = () => setStatusMap((prev) => {
      const next = pick(ids);
      return sameStatuses(prev, next) ? prev : next;
    });
    update();
    if (ids.length === 0) return;
    return watch({ ids, notify: update });
  }, [idsKey]);

  return statusMap;
}
