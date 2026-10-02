import type { AgentEvent } from "../../types/panel";
import { getCachedChatMessages, setCachedChatMessages, type CachedChatMessagesState } from "../chatMessagesCache";
import { subscribeAgentEvents } from "../useAgentEventBus";
import { chatRunReducer, type RunState } from "./chatRunReducer";

/**
 * Keeps a chat's run going while its tab is not on screen.
 *
 * Only the active tab is mounted (EditorGroupPane), so a chat in a background or
 * closed tab used to stop hearing its agent: on return it showed the stale
 * "Running tools…", then a reload merged the backend copy into that stale view.
 * Here one bus listener applies each event to the cached run state of any chat
 * that has a cache entry but no mounted pane, with the same reducer the pane
 * uses, so reopening the tab shows the run exactly where it is.
 */

const mounted = new Map<string, number>();
let installed = false;

export function snapshotOf(run: RunState): CachedChatMessagesState {
  return {
    messages: run.messages,
    streamBuffer: run.stream,
    streamThinking: run.thinking,
    optimisticRunning: run.status !== "idle",
    hasNewBelow: run.hasNewBelow,
    isAtBottom: run.atBottom,
    activeRunId: run.runId,
    stoppedRun: run.stopped,
    run,
  };
}

function onEvent(event: AgentEvent): void {
  const chatId = event.conv_id;
  if (!chatId || mounted.has(chatId)) return;
  const run = getCachedChatMessages(chatId)?.run;
  if (!run) return;
  const next = chatRunReducer(run, { type: "agentEvent", event });
  if (next !== run) setCachedChatMessages(chatId, snapshotOf(next));
}

export function installBackgroundRuns(): void {
  if (installed) return;
  installed = true;
  subscribeAgentEvents(onEvent);
}

/** A pane for this chat is on screen; it handles the chat's events itself. Returns the release. */
export function markChatMounted(chatId: string): () => void {
  mounted.set(chatId, (mounted.get(chatId) ?? 0) + 1);
  return () => {
    const left = (mounted.get(chatId) ?? 1) - 1;
    if (left > 0) mounted.set(chatId, left);
    else mounted.delete(chatId);
  };
}
