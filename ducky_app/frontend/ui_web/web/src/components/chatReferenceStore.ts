import { useSyncExternalStore } from "react";
import { getApi } from "../hooks/usePanelApi";
import { subscribePanelPush } from "../hooks/usePanelPushBus";

/**
 * The @ / slash catalog's raw lists, shared by every composer. Nothing loads on mount or
 * chat switch: the composer calls `ensureLoaded()` on the first '@' or '/'. After that,
 * pushes refresh only the list that changed (debounced 1 s).
 */

type Api = NonNullable<ReturnType<typeof getApi>>;

const LOADERS = {
  convs: (api: Api) => api.list_all_conversations(true).catch(() => []),
  profiles: (api: Api) => api.list_agent_profiles().catch(() => null),
  skills: (api: Api) => api.get_skill_info().catch(() => null),
  mcp: (api: Api) => api.list_mcp_servers?.().catch(() => null) ?? Promise.resolve(null),
  recents: (api: Api) => api.list_recent_projects().catch(() => []),
  paths: (api: Api) => api.list_project_file_paths().catch(() => null) as Promise<unknown>,
  workflows: (api: Api) => api.list_workflows?.().catch(() => null) ?? Promise.resolve(null),
};

export type ChatReferenceList = keyof typeof LOADERS;
export type ChatReferenceData = { [K in ChatReferenceList]: Awaited<ReturnType<(typeof LOADERS)[K]>> };
export type ChatReferenceStatus = "idle" | "loading" | "ready";
export interface ChatReferenceSnapshot {
  status: ChatReferenceStatus;
  data: Partial<ChatReferenceData>;
}

/** Push type → the lists it changes. Plugin panels/contributions refresh in usePluginContributions. */
const EVENT_LISTS: Record<string, ChatReferenceList[]> = {
  chats_changed: ["convs"],
  uefn_plugins_changed: ["mcp", "skills"],
  profiles_changed: ["profiles"],
  skills_changed: ["skills"],
  graphs_changed: ["workflows"],
  project_changed: ["recents", "paths"],
};

const REFRESH_DELAY_MS = 1000;

let snapshot: ChatReferenceSnapshot = { status: "idle", data: {} };
const listeners = new Set<() => void>();
let pending = new Set<ChatReferenceList>();
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let unsubscribePush: (() => void) | null = null;

function publish(next: ChatReferenceSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

async function loadLists(keys: ChatReferenceList[]): Promise<Partial<ChatReferenceData>> {
  const api = getApi();
  if (!api) return {};
  const values = await Promise.all(keys.map((key) => LOADERS[key](api)));
  const out: Partial<Record<ChatReferenceList, unknown>> = {};
  keys.forEach((key, index) => {
    out[key] = values[index];
  });
  return out as Partial<ChatReferenceData>;
}

function flushRefresh() {
  refreshTimer = null;
  const keys = [...pending];
  pending = new Set();
  if (!keys.length || snapshot.status !== "ready") return;
  void loadLists(keys).then((fresh) => {
    if (snapshot.status === "ready") publish({ status: "ready", data: { ...snapshot.data, ...fresh } });
  });
}

function onPush(event: { type?: unknown }) {
  const keys = EVENT_LISTS[String(event?.type || "")];
  if (!keys || snapshot.status !== "ready") return; // never loaded = nothing to refresh
  for (const key of keys) pending.add(key);
  // ponytail: the first push starts the 1 s timer and later ones ride along, so a steady
  // stream still refreshes once a second instead of never.
  if (!refreshTimer) refreshTimer = setTimeout(flushRefresh, REFRESH_DELAY_MS);
}

/** Load every list once; later calls do nothing. */
export function ensureLoaded(): void {
  if (snapshot.status !== "idle" || !getApi()) return;
  unsubscribePush ??= subscribePanelPush(onPush);
  publish({ status: "loading", data: snapshot.data });
  void loadLists(Object.keys(LOADERS) as ChatReferenceList[]).then((data) => {
    publish({ status: "ready", data });
  });
}

export function subscribeChatReferences(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getChatReferenceSnapshot(): ChatReferenceSnapshot {
  return snapshot;
}

export function useChatReferenceStore(): ChatReferenceSnapshot {
  return useSyncExternalStore(subscribeChatReferences, getChatReferenceSnapshot, getChatReferenceSnapshot);
}

export function _resetChatReferenceStoreForTests(): void {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  pending = new Set();
  unsubscribePush?.();
  unsubscribePush = null;
  snapshot = { status: "idle", data: {} };
  listeners.clear();
}
