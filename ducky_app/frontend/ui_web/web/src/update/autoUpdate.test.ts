// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AutoUpdateStatus } from "../types/panel";

const api = {
  get_auto_update_status: vi.fn(),
  apply_auto_update_now: vi.fn(),
  report_update_ui: vi.fn(),
};
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));

const {
  _resetBackgroundActivityForTests,
  dismissBackgroundJob,
  getBackgroundJobs,
  requestBackgroundJobAction,
  upsertBackgroundJob,
} = await import("../hooks/backgroundActivity");
const { UPDATE_JOB_ID, idleReport, startUpdateActivity, updateJobFor } = await import("./autoUpdate");
const { publishUnsavedFiles } = await import("./unsavedFiles");

function status(over: Partial<AutoUpdateStatus>): AutoUpdateStatus {
  return { phase: "idle", version: "1.2.412", ...over };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  _resetBackgroundActivityForTests();
  api.report_update_ui.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  api.get_auto_update_status.mockReset();
  api.apply_auto_update_now.mockReset();
});

describe("updateJobFor", () => {
  it("shows the download as a running job with its percent", () => {
    expect(updateJobFor(status({ phase: "downloading", done: 25, total: 100 }))).toMatchObject({
      id: UPDATE_JOB_ID,
      phase: "working",
      title: "Updating Ducky to 1.2.412",
      percent: 25,
    });
  });

  it("shows a downloaded update with what it waits for and an Update now button", () => {
    expect(updateJobFor(status({ phase: "ready", waiting_for: ["2 chats running"] }))).toMatchObject({
      phase: "done",
      title: "Update 1.2.412 downloaded",
      detail: "Switches when Ducky is idle · waits for 2 chats running",
      action: "Update now",
    });
  });

  it("says when it switched, failed, or shows nothing when there is no update", () => {
    expect(updateJobFor(status({ phase: "updated", previous: "1.2.410" }))).toMatchObject({
      phase: "done",
      title: "Updated to 1.2.412",
      detail: "From 1.2.410, without a restart",
    });
    expect(updateJobFor(status({ phase: "failed", error: "offline" }))).toMatchObject({ phase: "error", detail: "offline" });
    expect(updateJobFor(status({ phase: "idle" }))).toBeNull();
    expect(updateJobFor(status({ phase: "off" }))).toBeNull();
  });
});

describe("idleReport", () => {
  it("reports unsaved files and plugin jobs, not chats or the update itself", () => {
    const stop = publishUnsavedFiles(Symbol("editor"), 2);
    upsertBackgroundJob({ id: "render", source: "plugin", title: "Render trailer", phase: "working" });
    upsertBackgroundJob({ id: "turn", source: "agent", title: "Chat is working", phase: "working" });
    upsertBackgroundJob({ id: UPDATE_JOB_ID, source: "ducky-update", title: "Updating", phase: "working" });
    const now = Date.now();
    const report = idleReport(now - 90_000, now);
    expect(report).toMatchObject({ window: "main", dirty: 2, jobs: ["Render trailer"], idle_s: 90 });
    stop();
  });
});

describe("startUpdateActivity", () => {
  it("keeps the row in step, keeps a dismissed row gone, and Update now switches", async () => {
    api.get_auto_update_status.mockResolvedValue(status({ phase: "ready" }));
    api.apply_auto_update_now.mockResolvedValue({ ok: false, error: "Waits for: 1 chat running" });
    const stop = startUpdateActivity();
    await flush();
    expect(getBackgroundJobs().find((j) => j.id === UPDATE_JOB_ID)?.title).toBe("Update 1.2.412 downloaded");

    requestBackgroundJobAction(UPDATE_JOB_ID);
    await flush();
    expect(api.apply_auto_update_now).toHaveBeenCalledTimes(1);
    expect(getBackgroundJobs().find((j) => j.id === UPDATE_JOB_ID)?.detail).toBe("Waits for: 1 chat running");
    stop();

    // A dismissed row stays gone in this window; a fresh start (new poller) shows it again.
    dismissBackgroundJob(UPDATE_JOB_ID);
    const stop2 = startUpdateActivity();
    await flush();
    stop2();
    expect(getBackgroundJobs().some((j) => j.id === UPDATE_JOB_ID)).toBe(true);
  });
});
