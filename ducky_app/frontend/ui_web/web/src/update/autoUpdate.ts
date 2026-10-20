import {
  getBackgroundJobs,
  onBackgroundJobAction,
  upsertBackgroundJob,
  type BackgroundJob,
} from "../hooks/backgroundActivity";
import { getApi } from "../hooks/usePanelApi";
import { WINDOW_ID } from "../tabs/tabRegistryClient";
import type { AutoUpdateStatus, UpdateUiReport } from "../types/panel";
import { unsavedFileCount } from "./unsavedFiles";

/** The one background-activity row the auto-update keeps (frontend/update_swap.py). */
export const UPDATE_JOB_ID = "app-update";
const REPORT_MS = 30_000;
const POLL_BUSY_MS = 2_000;
const POLL_IDLE_MS = 30_000;

/** The activity row for an update status, or null when there is nothing to show. */
export function updateJobFor(status: AutoUpdateStatus | null | undefined): (Partial<BackgroundJob> & { id: string }) | null {
  if (!status) return null;
  const version = status.version || "";
  const base = { id: UPDATE_JOB_ID, source: "ducky-update" };
  switch (status.phase) {
    case "downloading": {
      const total = Number(status.total) || 0;
      const percent = total > 0 ? Math.min(100, Math.round(((Number(status.done) || 0) / total) * 100)) : null;
      return { ...base, phase: "working", title: `Updating Ducky to ${version}`, detail: "Getting only the files that changed", percent, action: "" };
    }
    case "switching":
      return { ...base, phase: "working", title: `Updating Ducky to ${version}`, detail: "Switching to the new version", percent: 100, action: "" };
    case "ready": {
      const waiting = status.waiting_for ?? [];
      const detail = waiting.length
        ? `Switches when Ducky is idle · waits for ${waiting.join(", ")}`
        : "Switches when Ducky is idle";
      return { ...base, phase: "done", title: `Update ${version} downloaded`, detail, percent: null, action: "Update now" };
    }
    case "failed":
      return { ...base, phase: "error", title: `Update ${version} didn't download`, detail: status.error || "Ducky tries again later", percent: null, action: "" };
    case "updated":
      return {
        ...base,
        phase: "done",
        title: `Updated to ${version}`,
        detail: status.previous ? `From ${status.previous}, without a restart` : "Without a restart",
        percent: null,
        action: "",
      };
    default:
      return null;
  }
}

/** What this window knows about being in use, for the switch's idle check. */
export function idleReport(lastInputAt: number, now: number = Date.now()): UpdateUiReport {
  const jobs = getBackgroundJobs()
    .filter((job) => job.phase === "working" && job.source !== "agent" && job.id !== UPDATE_JOB_ID)
    .map((job) => job.title);
  return {
    window: WINDOW_ID,
    visible: document.visibilityState === "visible",
    idle_s: Math.max(0, Math.round((now - lastInputAt) / 1000)),
    dirty: unsavedFileCount(),
    jobs,
  };
}

/** Report this window's idle state every 30 s and on every show/hide. Returns the stop. */
export function startUpdateReporting(): () => void {
  let lastInputAt = Date.now();
  const onInput = () => {
    lastInputAt = Date.now();
  };
  const report = () => {
    const api = getApi();
    if (api && typeof api.report_update_ui === "function") {
      void api.report_update_ui(idleReport(lastInputAt)).catch(() => {});
    }
  };
  const events = ["pointerdown", "keydown", "wheel"] as const;
  for (const name of events) window.addEventListener(name, onInput, { passive: true, capture: true });
  document.addEventListener("visibilitychange", report);
  const timer = window.setInterval(report, REPORT_MS);
  report();
  return () => {
    for (const name of events) window.removeEventListener(name, onInput, { capture: true });
    document.removeEventListener("visibilitychange", report);
    window.clearInterval(timer);
  };
}

/** Keep the activity row in step with the backend; its Update now button switches. Returns the stop. */
export function startUpdateActivity(): () => void {
  let stopped = false;
  let timer = 0;
  let shownKey = "";

  const poll = async () => {
    const api = getApi();
    let busy = false;
    if (api && typeof api.get_auto_update_status === "function") {
      try {
        const status = await api.get_auto_update_status();
        busy = status.phase === "downloading" || status.phase === "switching";
        const job = updateJobFor(status);
        const key = job ? `${status.phase}:${status.version}` : "";
        const present = getBackgroundJobs().some((j) => j.id === UPDATE_JOB_ID);
        // A row the person dismissed stays gone until the update moves on.
        if (job && (key !== shownKey || present)) upsertBackgroundJob({ ...job, ts: Date.now() });
        shownKey = key;
      } catch {
        // the next poll tries again
      }
    }
    if (!stopped) timer = window.setTimeout(() => void poll(), busy ? POLL_BUSY_MS : POLL_IDLE_MS);
  };

  const offAction = onBackgroundJobAction((id) => {
    if (id !== UPDATE_JOB_ID) return;
    const api = getApi();
    if (!api || typeof api.apply_auto_update_now !== "function") return;
    void api
      .apply_auto_update_now()
      .then((result) => {
        if (result && !result.ok && result.error) upsertBackgroundJob({ id: UPDATE_JOB_ID, detail: result.error });
      })
      .catch(() => {});
  });

  void poll();
  return () => {
    stopped = true;
    window.clearTimeout(timer);
    offAction();
  };
}
