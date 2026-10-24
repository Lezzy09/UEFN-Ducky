import { useEffect, useRef } from "react";
import type { AgentEvent } from "../types/panel";
import { installAgentEventBus, subscribeAgentEvents } from "./useAgentEventBus";

export interface RemoteConversation {
  id: string;
  title: string;
  folder_id?: string;
}

const RELOAD_DUCKIES_EVENT = "uefn-reload-duckies";
/** A swarm sends chats_changed per member event: one tree load per window, at its end. */
export const RELOAD_BATCH_MS = 400;

/** Ask the Duckies tree to reload after a group roster change. */
export function requestReloadDuckies(): void {
  window.dispatchEvent(new Event(RELOAD_DUCKIES_EVENT));
}

/** Sidebar reload is always ok; opening a tab is not (pipeline hubs stay in the list). */
export function shouldOpenCreatedChat(event: AgentEvent): boolean {
  return event.type === "chats_changed" && Boolean(event.conv_id) && event.open !== false;
}

/** Reload sidebar when MCP tools or linked agents create conversations. Chats and
 * groups deleted anywhere leave the tree at once (`onRemoved`), before the reload.
 * Reloads are batched: the first change starts a RELOAD_BATCH_MS window and one load
 * runs when it ends, however many changes came in it. */
export function useChatsChanged(
  load: () => Promise<void>,
  onCreated?: (conv: RemoteConversation) => void,
  onRemoved?: (convIds: string[], folderIds: string[]) => void,
) {
  const latest = useRef({ load, onCreated, onRemoved });
  latest.current = { load, onCreated, onRemoved };

  useEffect(() => {
    installAgentEventBus();
    let timer: number | undefined;
    const scheduleLoad = () => {
      if (timer !== undefined) return;
      timer = window.setTimeout(() => {
        timer = undefined;
        void latest.current.load();
      }, RELOAD_BATCH_MS);
    };
    const handler = (event: AgentEvent) => {
      if (event.type !== "chats_changed") return;
      const removedConvs = event.removed_conv_ids ?? [];
      const removedFolders = event.removed_folder_ids ?? [];
      if (removedConvs.length || removedFolders.length) latest.current.onRemoved?.(removedConvs, removedFolders);
      scheduleLoad();
      if (shouldOpenCreatedChat(event) && event.conv_id) {
        latest.current.onCreated?.({
          id: event.conv_id,
          title: event.title ?? "New ducky",
          folder_id: event.folder_id,
        });
      }
    };
    window.addEventListener(RELOAD_DUCKIES_EVENT, scheduleLoad);
    const unsubscribe = subscribeAgentEvents(handler);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(RELOAD_DUCKIES_EVENT, scheduleLoad);
      unsubscribe();
    };
  }, []);
}
