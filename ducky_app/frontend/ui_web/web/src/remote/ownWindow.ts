import { useSyncExternalStore } from "react";
import type { ResizeEdge } from "../utils/nativeWindowChrome";

type WebViewHost = { postMessage(message: unknown): void };

/**
 * The window showing another of your UEFN Duckies has no JS bridge (hideDesktopBridge),
 * yet its title bar must still move, resize and close this window. It posts straight to
 * pywebview's message handler, which takes only these window names for it
 * (win_frameless.install_sync_drag_bridge): nothing here reaches this Ducky's data.
 */
function post(name: string, params: unknown[]): boolean {
  const host = (window as Window & { chrome?: { webview?: WebViewHost } }).chrome?.webview;
  if (!host) return false;
  host.postMessage([name, JSON.stringify(params), name]);
  return true;
}

export type WindowChromeOp = "minimize" | "maximize" | "fullscreen" | "fit" | "close";

export const ownWindow = {
  /** While the left button is down: the OS moves the window (and snaps it). */
  move: () => post("uefnNativeWindowMove", []),
  resize: (edge: ResizeEdge, doubleClick = false) => post("uefnNativeWindowResize", [edge, doubleClick]),
  menu: () => post("uefnNativeWindowMenu", []),
  chrome: (op: WindowChromeOp, ...args: Array<number | boolean>) => post("uefnWindowChrome", [op, ...args]),
};

/** True while <html> has ``name`` (Python sets window-maximized / window-fullscreen). */
export function useHtmlClass(name: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const watch = new MutationObserver(onChange);
      watch.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      return () => watch.disconnect();
    },
    () => document.documentElement.classList.contains(name),
    () => false,
  );
}
