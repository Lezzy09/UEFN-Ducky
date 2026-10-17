/**
 * Locks, told through the alerts system whichever panels are open (a row in the header's
 * activity list, and a Windows notification when no Ducky window is in front):
 * - a plugin's write refused because someone holds the unit (also to the plugin's scope
 *   bar, which offers Ask to release);
 * - a teammate asking this PC to release a lock: a row with Release;
 * - a lock of this PC's broken, taken over or run out.
 */
import { onBackgroundJobAction, upsertBackgroundJob } from "../hooks/backgroundActivity";
import { getApi } from "../hooks/usePanelApi";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import { refusedWriteText } from "./scopeBarText";

export type RefusedWrite = {
  pluginId: string;
  unit?: string;
  name?: string;
  holder?: string;
  since?: number;
  error?: string;
};

type Listener = (write: RefusedWrite, text: string) => void;
const listeners = new Set<Listener>();
/** Plugin display names, as the scope bars last read them. */
const labels = new Map<string, string>();

export function rememberPluginLabel(pluginId: string, label: string | undefined): void {
  if (label) labels.set(pluginId, label);
}

/** The scope bars hear each refused write (the one of `write.pluginId` offers Ask to release). */
export function onRefusedWrite(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Tell the person: one activity row per unit (a repeat updates it) and one alert. */
export function alertRefusedWrite(write: RefusedWrite): string {
  const plugin = labels.get(write.pluginId) || write.pluginId;
  const text = refusedWriteText(plugin, write);
  upsertBackgroundJob({
    id: `scope-refused:${write.pluginId}:${write.unit || write.name || ""}`,
    source: "plugin-data",
    title: plugin,
    detail: text,
    phase: "error",
  });
  void getApi()?.notify_activity?.({ title: plugin, detail: text, phase: "error", seconds: 0 }).catch(() => false);
  for (const fn of [...listeners]) {
    try {
      fn(write, text);
    } catch {
      // A listener never breaks the alert.
    }
  }
  return text;
}

const ASKED = "scope-asked:";

/** The activity row of a teammate's ask: `scope-asked:<plugin>:<unit>` (plugin ids have no ':'). */
function askedRow(id: string): { pluginId: string; unit: string } | null {
  if (!id.startsWith(ASKED)) return null;
  const rest = id.slice(ASKED.length);
  const cut = rest.indexOf(":");
  return cut > 0 ? { pluginId: rest.slice(0, cut), unit: rest.slice(cut + 1) } : null;
}

async function releaseAsked(id: string): Promise<void> {
  const row = askedRow(id);
  if (!row) return;
  try {
    const out = await getApi()?.plugin_scope_unlock?.(row.pluginId, row.unit);
    if (out && out.ok === false) throw new Error(out.error || "It couldn't be released.");
    upsertBackgroundJob({ id, detail: "Released.", phase: "done", action: "" });
  } catch (err) {
    upsertBackgroundJob({ id, detail: err instanceof Error ? err.message : String(err), phase: "error" });
  }
}

let stop: (() => void) | null = null;

/**
 * Hear the backend's lock events app-wide: a refused write is alerted even when that plugin's
 * panel is closed (an agent's tool call), an ask gets a row with Release, a lost lock a row
 * saying so. Idempotent: the app and every scope bar call it.
 */
export function installScopeAlerts(): void {
  if (stop) return;
  installPanelPushBus();
  const stopPush = subscribePanelPush((event) => {
    const pluginId = event.plugin_id || "";
    if (!pluginId) return;
    const plugin = labels.get(pluginId) || pluginId;
    if (event.type === "plugin_write_refused") {
      alertRefusedWrite({
        pluginId, unit: event.unit, name: event.unit_name, holder: event.holder, since: event.since, error: event.error,
      });
    } else if (event.type === "plugin_lock_asked" && event.unit) {
      upsertBackgroundJob({
        id: `${ASKED}${pluginId}:${event.unit}`,
        source: "plugin-data",
        title: plugin,
        detail: `${event.holder || "A teammate"} asks you to release ${event.unit_name || event.unit}.`,
        phase: "done",
        action: "Release",
      });
    } else if (event.type === "plugin_lock_lost" && event.unit) {
      upsertBackgroundJob({
        id: `scope-lost:${pluginId}:${event.unit}`,
        source: "plugin-data",
        title: plugin,
        detail: event.detail || `Your lock on ${event.unit_name || event.unit} ended.`,
        phase: "error",
      });
    }
  });
  const stopAction = onBackgroundJobAction((id) => {
    void releaseAsked(id);
  });
  stop = () => {
    stopPush();
    stopAction();
  };
}

/** Tests: stop hearing, so the next install starts afresh. */
export function _resetScopeAlertsForTests(): void {
  stop?.();
  stop = null;
}

/** A panel's `data.*` / `files.*` answer that refused the write over a lock, or null. */
export function refusedFromResult(pluginId: string, out: Record<string, unknown> | undefined): RefusedWrite | null {
  if (!out || out.ok !== false) return null;
  const lock = (out.lock ?? null) as { unit?: string; name?: string; holder?: string; since?: number } | null;
  if (out.code !== "locked" && !(out.code === "read_only" && lock)) return null;
  return {
    pluginId,
    unit: lock?.unit,
    name: lock?.name,
    holder: lock?.holder,
    since: lock?.since,
    error: String(out.error || ""),
  };
}
