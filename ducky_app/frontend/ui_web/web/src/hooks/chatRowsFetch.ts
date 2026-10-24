import type { ChatMessage } from "../types/panel";
import { callOverHttp, canCallOverHttp } from "./panelHttp";
import { getApi } from "./usePanelApi";

/** Longest a chat load may take before the pane stops waiting and offers Retry. */
export const CHAT_LOAD_TIMEOUT_MS = 45_000;

export class ChatLoadTimeout extends Error {
  constructor() {
    super("timed out");
    this.name = "ChatLoadTimeout";
  }
}

/** `promise`, or a ChatLoadTimeout once `ms` pass without it settling. */
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new ChatLoadTimeout()), ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (err: unknown) => {
        window.clearTimeout(timer);
        reject(err);
      },
    );
  });
}

/**
 * A chat's rows. In the desktop app a long chat is megabytes of JSON; pywebview hands
 * every reply back as one injected script, and a reply that size can stall the page
 * until the WebView is reloaded, so the chat never loads. The page is served by the same
 * local server that answers `/__panel_api`, so ask over plain HTTP first and keep the
 * bridge as the fallback (dev server, or a build without the route).
 */
export async function fetchChatRows(chatId: string, timeoutMs = CHAT_LOAD_TIMEOUT_MS): Promise<ChatMessage[]> {
  const api = getApi();
  if (!api) return [];
  if (canCallOverHttp()) {
    const http = await callOverHttp("load_messages", [chatId], timeoutMs);
    if (http.ok && Array.isArray(http.result)) return http.result as ChatMessage[];
    if (!http.ok && http.timedOut) throw new ChatLoadTimeout();
    // Any other failure: fall through to the bridge.
  }
  const rows: unknown = await withTimeout(api.load_messages(chatId), timeoutMs);
  // On a phone a relay blip or a 502 answers with nothing at all: that is a failed load
  // (the chat says so and retries), never an empty or missing list to render.
  if (!Array.isArray(rows)) throw new Error("no messages came back (the connection dropped)");
  return rows as ChatMessage[];
}
