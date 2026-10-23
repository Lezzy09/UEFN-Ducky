/**
 * Phone app only: keeps live voice running with the screen locked. The Android
 * shell's `LiveVoice` plugin runs a foreground service while any chat is live;
 * desktop and browsers have no plugin, so every call here is a no-op there.
 */

type LiveVoicePlugin = {
  start: () => Promise<unknown>;
  stop: () => Promise<unknown>;
};

/** The notification's Stop button (sent by the Android shell). */
export const NATIVE_LIVE_VOICE_STOP = "ud:live-voice-stop";

let running = false;
let stoppedByNotification = false;

function plugin(): LiveVoicePlugin | null {
  const cap = (globalThis as { Capacitor?: { Plugins?: Record<string, unknown> } }).Capacitor;
  const p = cap?.Plugins?.LiveVoice as Partial<LiveVoicePlugin> | undefined;
  if (!p || typeof p.start !== "function" || typeof p.stop !== "function") return null;
  return p as LiveVoicePlugin;
}

/** Start on the first live chat, stop after the last. */
export function syncNativeKeepAlive(liveCount: number): void {
  const want = liveCount > 0;
  if (stoppedByNotification) {
    // Chats end one by one after the notification's Stop: don't restart in between.
    if (!want) stoppedByNotification = false;
    return;
  }
  if (want === running) return;
  const p = plugin();
  if (!p) return;
  running = want;
  const call = want ? p.start() : p.stop();
  // Refused (no mic permission, app in the background): live voice still works on screen.
  void Promise.resolve(call).catch(() => {
    if (want) running = false;
  });
}

/**
 * Ends live voice when the notification's Stop is pressed. `endAll` returns how
 * many live chats it is ending. Returns an unsubscribe.
 */
export function onNativeLiveVoiceStop(endAll: () => number): () => void {
  if (typeof document === "undefined") return () => {};
  const fn = () => {
    // The service already stopped itself: no stop() call back.
    running = false;
    stoppedByNotification = endAll() > 0;
  };
  document.addEventListener(NATIVE_LIVE_VOICE_STOP, fn);
  return () => document.removeEventListener(NATIVE_LIVE_VOICE_STOP, fn);
}
