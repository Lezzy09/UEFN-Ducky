/**
 * A window showing another of your UEFN Duckies is served by this Ducky's own panel
 * server, so it shares this app's localStorage and hears its "storage" events: hiding
 * the sidebar there hid it in this app's main window, and the main window's layout
 * showed up there. That window keeps its own copy of every key, one copy per Ducky it
 * shows, and hears only changes to those.
 *
 * Imported first in main.tsx: modules read localStorage while they load.
 */

const PREFIX = "ducky-remote:";

/** The keys of one remote Ducky window, stored in this app's localStorage under a prefix. */
export function isolateLocalStorage(win: Window, scope: string): void {
  let real: Storage;
  try {
    real = win.localStorage;
  } catch {
    return;
  }
  const prefix = `${PREFIX}${scope}:`;
  const ownKeys = (): string[] => {
    const keys: string[] = [];
    for (let i = 0; i < real.length; i += 1) {
      const key = real.key(i);
      if (key?.startsWith(prefix)) keys.push(key.slice(prefix.length));
    }
    return keys;
  };
  const scoped = {
    get length() {
      return ownKeys().length;
    },
    key: (index: number) => ownKeys()[index] ?? null,
    getItem: (key: string) => real.getItem(prefix + String(key)),
    setItem: (key: string, value: string) => real.setItem(prefix + String(key), String(value)),
    removeItem: (key: string) => real.removeItem(prefix + String(key)),
    clear: () => {
      for (const key of ownKeys()) real.removeItem(prefix + key);
    },
  } as Storage;
  try {
    Object.defineProperty(win, "localStorage", { configurable: true, get: () => scoped });
  } catch {
    return;
  }
  // Runs before every other listener: other windows' keys never reach this page, and
  // this window's own keys arrive under their plain names.
  win.addEventListener(
    "storage",
    (ev) => {
      if (ev.storageArea !== real) return;
      ev.stopImmediatePropagation();
      if (!ev.key?.startsWith(prefix)) return;
      win.dispatchEvent(
        new StorageEvent("storage", {
          key: ev.key.slice(prefix.length),
          oldValue: ev.oldValue,
          newValue: ev.newValue,
          url: ev.url,
        }),
      );
    },
    true,
  );
}

if (typeof window !== "undefined") {
  const q = new URLSearchParams(window.location.search);
  if (q.get("direct") === "ducky") isolateLocalStorage(window, q.get("to") || "ducky");
}
