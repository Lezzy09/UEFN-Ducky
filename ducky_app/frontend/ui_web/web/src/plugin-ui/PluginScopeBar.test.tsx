// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import { PluginScopeBar } from "./PluginScopeBar";

const api = vi.hoisted(() => ({
  plugin_scope_status: vi.fn(),
  plugin_scope_choices: vi.fn(),
  plugin_scope_set: vi.fn(),
  plugin_scope_sync: vi.fn(),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
const push = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("../hooks/usePanelPushBus", () => ({
  installPanelPushBus: () => {},
  subscribePanelPush: (fn: (event: Record<string, unknown>) => void) => {
    push.handlers.add(fn);
    return () => push.handlers.delete(fn);
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const bar = () =>
  render(
    <ConfirmModalProvider>
      <PluginScopeBar pluginId="brainrot-tcg" onScopeChanged={() => {}} />
    </ConfirmModalProvider>,
  );

describe("plugin scope bar", () => {
  it("renders nothing while the account has no shared spaces", async () => {
    api.plugin_scope_status.mockResolvedValue({ ok: true, visible: false, scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false } });
    const { container } = bar();
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(api.plugin_scope_sync).not.toHaveBeenCalled();
  });

  it("shows whose data it is, syncs the space, and confirms before switching", async () => {
    api.plugin_scope_status.mockResolvedValue({
      ok: true, visible: true, pluginLabel: "BrainRot TCG", email: "ana@x.org", canChange: true, members: 4, state: "ok", pending: 0,
      syncedAt: Date.now() / 1000 - 5, usage: { usedBytes: 34 * 1024 ** 2, limitBytes: 5 * 1024 ** 3 },
      scope: { kind: "shared", label: "Alpha Studio", spaceId: "s1", readOnly: false },
    });
    api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
      { id: "personal", kind: "personal", label: "Local" },
      { id: "s1", kind: "shared", label: "Alpha Studio", members: 4 },
    ] });
    api.plugin_scope_set.mockResolvedValue({ ok: true });
    bar();
    expect((await screen.findByText("Alpha Studio")).className).toContain("plugin-scope-bar__badge--shared");
    expect(screen.getByText("shared with 4 members")).toBeTruthy();
    expect(screen.getByText("34 MB of 5 GB")).toBeTruthy();
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("brainrot-tcg", false));
    expect(api.plugin_scope_status).toHaveBeenCalledWith("brainrot-tcg");

    fireEvent.click(screen.getByRole("button", { name: "Change ▾" }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "Local" }));
    expect(await screen.findByText("Switch BrainRot TCG to Local data?")).toBeTruthy();
    expect(screen.getByText("Nothing is copied. BrainRot TCG restarts with its Local data.")).toBeTruthy();
    expect(api.plugin_scope_set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Switch/ }));
    await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("brainrot-tcg", "personal"));
  });

  it("Sync now forces a round and waits for its result", async () => {
    api.plugin_scope_status.mockResolvedValue({
      ok: true, visible: true, canChange: true, state: "ok", pending: 9, syncedAt: Date.now() / 1000 - 3120,
      scope: { kind: "shared", label: "test", spaceId: "s1", readOnly: false },
    });
    api.plugin_scope_sync.mockResolvedValue({ ok: true, started: true });
    bar();
    expect(await screen.findByText("Synced 52 min ago · 9 changes waiting")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("brainrot-tcg", true));
    expect((screen.getByRole("button", { name: "Syncing…" }) as HTMLButtonElement).disabled).toBe(true);

    api.plugin_scope_status.mockResolvedValue({
      ok: true, visible: true, canChange: true, state: "error", pending: 9, error: "Sync failed: HTTPException: boom",
      syncedAt: Date.now() / 1000 - 3120, scope: { kind: "shared", label: "test", spaceId: "s1", readOnly: false },
    });
    push.handlers.forEach((fn) => fn({ type: "plugin_scope_changed", plugins: [], synced: true }));
    expect(await screen.findByRole("button", { name: "Sync now" })).toBeTruthy();
    expect(await screen.findByText("Sync failed: HTTPException: boom")).toBeTruthy();
    expect(screen.getByText("Not synced · 9 changes waiting")).toBeTruthy();
  });
});
