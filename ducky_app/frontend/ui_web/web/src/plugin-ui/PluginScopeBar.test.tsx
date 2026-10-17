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
  plugin_scope_retry: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_drop: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  space_reset_settle: vi.fn() as ReturnType<typeof vi.fn> | undefined,
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
const retryFn = api.plugin_scope_retry;
const dropFn = api.plugin_scope_drop;
const settleFn = api.space_reset_settle;
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  api.plugin_scope_retry = retryFn;
  api.plugin_scope_drop = dropFn;
  api.space_reset_settle = settleFn;
});

const bar = () =>
  render(
    <ConfirmModalProvider>
      <PluginScopeBar pluginId="brainrot-tcg" onScopeChanged={() => {}} />
    </ConfirmModalProvider>,
  );

/** A shared copy's status, with ``extra`` on top (``scope`` fields merge too). */
const sharedStatus = (extra: Record<string, unknown> = {}, scope: Record<string, unknown> = {}) => ({
  ok: true, visible: true, pluginLabel: "BrainRot TCG", canChange: true, state: "ok", pending: 0,
  syncedAt: Date.now() / 1000 - 5, ...extra,
  scope: { kind: "shared", label: "Alpha Studio", spaceId: "s1", readOnly: false, ...scope },
});

describe("plugin scope bar", () => {
  it("renders nothing while the account has no shared spaces", async () => {
    api.plugin_scope_status.mockResolvedValue({ ok: true, visible: false, scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false } });
    const { container } = bar();
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(api.plugin_scope_sync).not.toHaveBeenCalled();
  });

  it("says Local only for a plugin that keeps its own files, with nothing to switch", async () => {
    api.plugin_scope_status.mockResolvedValue({
      ok: true, visible: true, shareable: false, canChange: true, state: "ok",
      scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false },
    });
    bar();
    expect(await screen.findByText("Local only: this plugin keeps its own files")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Change ▾" })).toBeNull();
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
    expect(api.plugin_scope_sync).not.toHaveBeenCalled();
  });

  it("shows whose data it is, syncs the space, and confirms before switching", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      email: "ana@x.org", members: 4, usage: { usedBytes: 34 * 1024 ** 2, limitBytes: 5 * 1024 ** 3 },
    }));
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

  it("the switch confirm counts the changes still to send, as of the click", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ pending: 1 }));
    api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
      { id: "personal", kind: "personal", label: "Local" },
      { id: "s1", kind: "shared", label: "Alpha Studio" },
    ] });
    bar();
    expect(await screen.findByText(/1 change waiting/)).toBeTruthy();
    // More changes landed since the bar last refreshed: the confirm reads them again.
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      pending: 3, blocked: 1, items: [{ kind: "doc", key: "scene_1", state: "blocked", attempts: 5 }],
    }));
    fireEvent.click(screen.getByRole("button", { name: "Change ▾" }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "Local" }));
    expect(
      await screen.findByText(
        "3 changes not sent to Alpha Studio will be sent first. 1 change not shared stays in Alpha Studio's copy on this PC. " +
          "Nothing is copied. BrainRot TCG restarts with its Local data.",
      ),
    ).toBeTruthy();
  });

  it("asks for one sync on open and one on focus, never on a timer", async () => {
    const every = vi.spyOn(window, "setInterval");
    try {
      api.plugin_scope_status.mockResolvedValue(sharedStatus());
      bar();
      await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledTimes(1));
      expect(every.mock.calls.filter(([, ms]) => Number(ms) >= 10_000)).toEqual([]);
      fireEvent.focus(window);
      expect(api.plugin_scope_sync).toHaveBeenCalledTimes(2);
      expect(api.plugin_scope_sync).toHaveBeenLastCalledWith("brainrot-tcg", false);
    } finally {
      every.mockRestore();
    }
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

  it("without a provider, says it isn't connected, keeps the queue count, and Sync now says why", async () => {
    const why = "Not connected: Ducky Account isn't running";
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ state: "no_provider", pending: 2, error: why }));
    api.plugin_scope_sync.mockResolvedValue({ ok: false, started: false, error: why });
    bar();
    expect(await screen.findByText(`${why} · 2 changes waiting`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("brainrot-tcg", true));
    expect(((await screen.findByRole("button", { name: "Sync now" })) as HTMLButtonElement).disabled).toBe(false);
    // The answer's reason is the one already on the bar: said once.
    expect(screen.getAllByText(new RegExp(why)).length).toBe(1);
  });

  it("an unavailable copy is read-only with its reason, said once", async () => {
    const why = "permission denied: uefn-ducky-store.teams";
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ state: "unavailable", error: why }, { readOnly: true }));
    bar();
    expect(
      await screen.findByText(`Alpha Studio isn't available right now (${why}). Read-only until it's back.`),
    ).toBeTruthy();
    expect(screen.getAllByText(new RegExp(why)).length).toBe(1);
    expect(screen.getByRole("button", { name: "Sync now" })).toBeTruthy();
  });

  it("lists each change that isn't shared with its reason; Retry sends it again, Drop asks first", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      pending: 0, refused: 1, blocked: 1, conflict: 1,
      items: [
        { kind: "asset", key: "art/big.png", state: "refused", reason: "too big for your plan" },
        { kind: "doc", key: "scene_1", state: "blocked", attempts: 5 },
        { kind: "doc", key: "deck", state: "conflict" },
      ],
    }));
    api.plugin_scope_retry?.mockResolvedValue({ ok: true });
    api.plugin_scope_drop?.mockResolvedValue({ ok: true });
    api.plugin_scope_sync.mockResolvedValue({ ok: true, started: true });
    bar();
    expect(await screen.findByText("Not shared: 3")).toBeTruthy();
    expect(screen.getByText("art/big.png: too big for your plan")).toBeTruthy();
    expect(screen.getByText("scene_1: couldn't be sent after 5 tries")).toBeTruthy();
    expect(screen.getByText("deck: changed here and by someone else")).toBeTruthy();
    // A conflict has no Retry or Drop here.
    expect(screen.queryByRole("button", { name: "Retry deck" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry scene_1" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenCalledWith("brainrot-tcg", "scene_1"));
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("brainrot-tcg", true));

    fireEvent.click(screen.getByRole("button", { name: "Retry all" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenLastCalledWith("brainrot-tcg"));

    fireEvent.click(screen.getByRole("button", { name: "Drop my change to art/big.png" }));
    expect(await screen.findByText("Drop your change to art/big.png?")).toBeTruthy();
    expect(screen.getByText("It is removed from this PC and never sent to Alpha Studio.")).toBeTruthy();
    expect(api.plugin_scope_drop).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Drop my change \(/ }));
    await waitFor(() => expect(api.plugin_scope_drop).toHaveBeenCalledWith("brainrot-tcg", "asset", "art/big.png"));
  });

  it("shows a failed Retry's reason, and no Retry / Drop without the host calls", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      blocked: 1, items: [{ kind: "doc", key: "scene_1", state: "blocked", reason: "file in use" }],
    }));
    api.plugin_scope_retry?.mockResolvedValue({ ok: false, error: "Couldn't requeue scene_1." });
    const view = bar();
    fireEvent.click(await screen.findByRole("button", { name: "Retry scene_1" }));
    expect(await screen.findByText("Couldn't requeue scene_1.")).toBeTruthy();
    expect(api.plugin_scope_sync).not.toHaveBeenCalledWith("brainrot-tcg", true);
    view.unmount();

    api.plugin_scope_retry = undefined;
    api.plugin_scope_drop = undefined;
    bar();
    expect(await screen.findByText("scene_1: file in use")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Drop my change/ })).toBeNull();
  });

  it("keeps the list short until Show all", async () => {
    const items = ["a", "b", "c", "d", "e"].map((key) => ({ kind: "doc", key, state: "refused", reason: "storage full" }));
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ refused: 7, items }));
    bar();
    expect(await screen.findByText("Not shared: 7")).toBeTruthy();
    expect(screen.queryByText("d: storage full")).toBeNull();
    expect(screen.getByText("2 more not listed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all 5" }));
    expect(screen.getByText("e: storage full")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show fewer" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("after a reset on the server, offers Upload my copy and Clear my copy for the whole copy, each asked first", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      state: "reset", kindLabel: "Team", resetContents: ["BrainRot TCG", "Forge", "Workflows"],
      refused: 2, items: [
        { kind: "doc", key: "card.a", state: "refused", reason: "storage full" },
        { kind: "doc", key: "card.b", state: "refused", reason: "storage full" },
      ],
    }, { readOnly: true }));
    api.space_reset_settle?.mockResolvedValue({ ok: true });
    bar();
    expect(
      await screen.findByText(
        "Alpha Studio's team data was reset on the server. Your copy here is read-only until you choose what to do with it.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
    // Retry all, Retry and Drop wait for the choice: Retry all once uploaded the whole copy unasked.
    expect(screen.getByText("card.a: storage full")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry all" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Retry / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Drop my change to/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Upload my copy" }));
    expect(await screen.findByText("Upload your copy of Alpha Studio?")).toBeTruthy();
    expect(screen.getByText(
      "This PC's whole copy of Alpha Studio's data is sent again, and everyone in Alpha Studio gets it: BrainRot TCG, Forge and Workflows.",
    )).toBeTruthy();
    expect(api.space_reset_settle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Upload my copy \(/ }));
    await waitFor(() => expect(api.space_reset_settle).toHaveBeenCalledWith("s1", "upload"));

    fireEvent.click(screen.getByRole("button", { name: "Clear my copy" }));
    expect(await screen.findByText("Clear your copy of Alpha Studio?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Yes, clear it/ }));
    await waitFor(() => expect(api.space_reset_settle).toHaveBeenCalledWith("s1", "clear"));
    expect(api.plugin_scope_retry).not.toHaveBeenCalled();
    expect(api.plugin_scope_drop).not.toHaveBeenCalled();
  });

  it("after a reset, without the host call, says read-only and offers no choice", async () => {
    api.space_reset_settle = undefined;
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ state: "reset", kindLabel: "Team" }, { readOnly: true }));
    bar();
    expect(await screen.findByText("Alpha Studio's team data was reset on the server. Your copy here is read-only.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Upload my copy" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear my copy" })).toBeNull();
  });
});
