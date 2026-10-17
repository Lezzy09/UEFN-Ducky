// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { _resetBackgroundActivityForTests, getBackgroundJobs, requestBackgroundJobAction } from "../hooks/backgroundActivity";
import { _resetScopeAlertsForTests, installScopeAlerts, onRefusedWrite } from "./scopeAlerts";

const api = vi.hoisted(() => ({ plugin_scope_unlock: vi.fn(), notify_activity: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
const push = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("../hooks/usePanelPushBus", () => ({
  installPanelPushBus: () => {},
  subscribePanelPush: (fn: (event: Record<string, unknown>) => void) => {
    push.handlers.add(fn);
    return () => push.handlers.delete(fn);
  },
}));
const send = (event: Record<string, unknown>) => push.handlers.forEach((fn) => fn(event));

afterEach(() => {
  _resetScopeAlertsForTests();
  _resetBackgroundActivityForTests();
  vi.clearAllMocks();
});

describe("scope alerts, app-wide", () => {
  it("a write refused while the plugin's panel is closed is still told, once", () => {
    installScopeAlerts();
    installScopeAlerts();
    api.notify_activity.mockResolvedValue(true);
    const heard: string[] = [];
    const stopHearing = onRefusedWrite((_, text) => heard.push(text));
    send({ type: "plugin_write_refused", plugin_id: "forge", unit: "doc:scene.a", unit_name: "Scene A", holder: "Ana" });
    stopHearing();
    expect(heard).toEqual(["forge: Scene A is locked by Ana. Your change wasn't saved."]);
    expect(getBackgroundJobs()).toEqual([expect.objectContaining({ title: "forge", phase: "error", detail: heard[0] })]);
    expect(api.notify_activity).toHaveBeenCalledTimes(1);
  });

  it("a teammate's ask is a row with Release, which releases the lock", async () => {
    installScopeAlerts();
    api.plugin_scope_unlock.mockResolvedValue({ ok: true });
    send({ type: "plugin_lock_asked", plugin_id: "forge", unit: "doc:scene.a", unit_name: "Scene A", holder: "Ben" });
    const [row] = getBackgroundJobs();
    expect(row).toEqual(expect.objectContaining({ title: "forge", detail: "Ben asks you to release Scene A.", action: "Release" }));
    requestBackgroundJobAction(row.id);
    await vi.waitFor(() => expect(getBackgroundJobs()[0]).toEqual(expect.objectContaining({ detail: "Released." })));
    expect(getBackgroundJobs()[0].action).toBeUndefined();
    expect(api.plugin_scope_unlock).toHaveBeenCalledTimes(1);
    expect(api.plugin_scope_unlock).toHaveBeenCalledWith("forge", "doc:scene.a");
  });

  it("a release that fails keeps Release and says why", async () => {
    installScopeAlerts();
    api.plugin_scope_unlock.mockResolvedValue({ ok: false, error: "offline" });
    send({ type: "plugin_lock_asked", plugin_id: "forge", unit: "doc:scene.a", holder: "Ben" });
    requestBackgroundJobAction(getBackgroundJobs()[0].id);
    await vi.waitFor(() => expect(getBackgroundJobs()[0]).toEqual(expect.objectContaining({ detail: "offline", phase: "error", action: "Release" })));
  });

  it("a lock of mine that went is told", () => {
    installScopeAlerts();
    send({ type: "plugin_lock_lost", plugin_id: "forge", unit: "doc:scene.a", unit_name: "Scene A", holder: "Ben", kept: true,
      detail: "Ben took Scene A; your unsent change is kept as a conflict." });
    expect(getBackgroundJobs()).toEqual([expect.objectContaining({
      title: "forge", phase: "error", detail: "Ben took Scene A; your unsent change is kept as a conflict." })]);
  });
});
