// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import { _resetBackgroundActivityForTests, getBackgroundJobs } from "../hooks/backgroundActivity";
import { PluginScopeBar } from "./PluginScopeBar";

const api = vi.hoisted(() => ({
  plugin_scope_status: vi.fn(),
  plugin_scope_choices: vi.fn(),
  plugin_scope_set: vi.fn(),
  plugin_scope_sync: vi.fn(),
  plugin_scope_retry: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_drop: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  space_reset_settle: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_push: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_pull: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_ask: vi.fn(),
  notify_activity: vi.fn(),
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
const saved = { retry: api.plugin_scope_retry, drop: api.plugin_scope_drop, settle: api.space_reset_settle,
  push: api.plugin_scope_push, pull: api.plugin_scope_pull };
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  Object.assign(api, { plugin_scope_retry: saved.retry, plugin_scope_drop: saved.drop, space_reset_settle: saved.settle,
    plugin_scope_push: saved.push, plugin_scope_pull: saved.pull });
  localStorage.clear();
  _resetBackgroundActivityForTests();
});

const bar = (pluginId = "brainrot-tcg") =>
  render(
    <ConfirmModalProvider>
      <PluginScopeBar pluginId={pluginId} onScopeChanged={() => {}} />
    </ConfirmModalProvider>,
  );

/** A shared copy's status, with ``extra`` on top (``scope`` fields merge too). */
const sharedStatus = (extra: Record<string, unknown> = {}, scope: Record<string, unknown> = {}) => ({
  ok: true, visible: true, pluginLabel: "BrainRot TCG", canChange: true, state: "ok", pending: 0,
  syncedAt: Date.now() / 1000 - 5, ...extra,
  scope: { kind: "shared", label: "Alpha Studio", spaceId: "s1", readOnly: false, ...scope },
});

const line = () => screen.getByRole("status");

describe("plugin scope bar", () => {
  it("renders nothing while the account has no shared spaces", async () => {
    api.plugin_scope_status.mockResolvedValue({ ok: true, visible: false, scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false } });
    const { container } = bar();
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(api.plugin_scope_sync).not.toHaveBeenCalled();
  });

  it("renders nothing for a plugin that can't share, even from an app that still sends it visible", async () => {
    api.plugin_scope_status.mockResolvedValue({
      ok: true, visible: true, shareable: false, canChange: true, state: "ok",
      scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false },
    });
    const { container } = bar();
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(api.plugin_scope_sync).not.toHaveBeenCalled();
  });

  it("is one line: scope and Change, one phrase, people, locks, Sync now and Details", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      head: 482, syncedAt: Date.now() / 1000 - 120,
      people: [
        { user_name: "Ana", plugins: { "brainrot-tcg": { editing: [{ unitName: "MEGA_Duel_Stadium", actor: "user" }] } } },
        { user_name: "Ben", plugins: { "brainrot-tcg": { editing: [{ unitName: "Arena", actor: "agent", ducky: "Builder" }] } } },
        { user_name: "Cy", plugins: { "brainrot-tcg": { viewing: true } } },
        { user_name: "Me", me: true, plugins: { "brainrot-tcg": { viewing: true } } },
      ],
      locks: [{ unit: "doc:deck", name: "deck", holder: "Ana", mine: false }, { unit: "doc:pack", name: "pack", mine: true }],
    }));
    bar();
    expect(await screen.findByText("Locked by Ana: deck (read-only for you)")).toBeTruthy();
    const status = line();
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(within(status).getByText("with Ana (editing MEGA_Duel_Stadium), Ben's ducky Builder +1")).toBeTruthy();
    expect(within(status).getByText("1 locked · You hold 1")).toBeTruthy();
    // Left to right: the scope, Change, then the phrase.
    const text = status.textContent ?? "";
    expect(text.indexOf("Alpha Studio")).toBeLessThan(text.indexOf("Change ▾"));
    expect(text.indexOf("Change ▾")).toBeLessThan(text.indexOf("Locked by Ana"));
    expect(within(status).getByRole("button", { name: "Sync now" })).toBeTruthy();
    expect(within(status).getByRole("button", { name: "Details ▾" }).getAttribute("aria-expanded")).toBe("false");
    // Nothing of the drawer until Details.
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("Details opens the drawer under the line and remembers it per plugin", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      email: "ana@x.org", members: 4, usage: { usedBytes: 34 * 1024 ** 2, limitBytes: 5 * 1024 ** 3 },
    }));
    const view = bar();
    fireEvent.click(await screen.findByRole("button", { name: "Details ▾" }));
    const drawer = screen.getByRole("region", { name: "Sync details: Alpha Studio" });
    expect(within(drawer).getByText("Signed in as ana@x.org · 4 members")).toBeTruthy();
    expect(within(drawer).getByText("34 MB of 5 GB")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Details ▾" }).getAttribute("aria-expanded")).toBe("true");
    expect(localStorage.getItem("ducky.pluginScopeDrawer.brainrot-tcg")).toBe("1");
    view.unmount();

    // Open again for this plugin; another plugin starts closed.
    bar();
    expect(await screen.findByRole("region", { name: "Sync details: Alpha Studio" })).toBeTruthy();
    cleanup();
    bar("forge");
    await screen.findByRole("button", { name: "Details ▾" });
    expect(screen.queryByRole("region")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Details ▾" }));
    fireEvent.click(screen.getByRole("button", { name: "Details ▾" }));
    expect(localStorage.getItem("ducky.pluginScopeDrawer.forge")).toBeNull();
  });

  it("starts closed when the browser's storage is off", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    api.plugin_scope_status.mockResolvedValue(sharedStatus());
    bar();
    fireEvent.click(await screen.findByRole("button", { name: "Details ▾" }));
    expect(screen.getByRole("region", { name: "Sync details: Alpha Studio" })).toBeTruthy();
  });

  it("confirms before switching, counting the changes still to send as of the click", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ pending: 1 }));
    api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
      { id: "personal", kind: "personal", label: "Local" },
      { id: "s1", kind: "shared", label: "Alpha Studio" },
    ] });
    api.plugin_scope_set.mockResolvedValue({ ok: true });
    bar();
    expect(await screen.findByText("1 to send")).toBeTruthy();
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
    expect(api.plugin_scope_set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Switch/ }));
    await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("brainrot-tcg", "personal"));
  });

  it("asks for one sync on open and one on focus, never on a timer", async () => {
    const every = vi.spyOn(window, "setInterval");
    api.plugin_scope_status.mockResolvedValue(sharedStatus());
    bar();
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledTimes(1));
    expect(every.mock.calls.filter(([, ms]) => Number(ms) >= 10_000)).toEqual([]);
    fireEvent.focus(window);
    expect(api.plugin_scope_sync).toHaveBeenCalledTimes(2);
    expect(api.plugin_scope_sync).toHaveBeenLastCalledWith("brainrot-tcg", false);
  });

  it("Sync now forces a round and waits for its result; a failed round says why once", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ pending: 9, syncedAt: Date.now() / 1000 - 3120 }));
    api.plugin_scope_sync.mockResolvedValue({ ok: true, started: true });
    bar();
    expect(await screen.findByText("9 to send")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("brainrot-tcg", true));
    expect((screen.getByRole("button", { name: "Syncing…" }) as HTMLButtonElement).disabled).toBe(true);

    const why = "Sync failed: HTTPException: boom";
    api.plugin_scope_status.mockResolvedValue(sharedStatus({
      state: "error", pending: 9, error: why, nextTry: Date.now() / 1000 + 40,
    }));
    push.handlers.forEach((fn) => fn({ type: "plugin_scope_changed", plugins: [], synced: true }));
    expect(await screen.findByRole("button", { name: "Sync now" })).toBeTruthy();
    expect(await screen.findByText(new RegExp(`^Not synced: ${why} · retry in (39|40) s$`))).toBeTruthy();
    expect(screen.getAllByText(new RegExp(why)).length).toBe(1);
  });

  it("without a provider, says it isn't connected, keeps the queue count, and Sync now says why", async () => {
    const why = "Not connected: Ducky Account isn't running";
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ state: "no_provider", pending: 2, error: why }));
    api.plugin_scope_sync.mockResolvedValue({ ok: false, started: false, error: why });
    bar();
    expect(await screen.findByText(`${why} · 2 to send`)).toBeTruthy();
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

  it("in Manual mode offers Push and Pull instead of Sync now", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ mode: "manual", head: 3, pending: 2 }));
    api.plugin_scope_push?.mockResolvedValue({ ok: true, started: true });
    api.plugin_scope_pull?.mockResolvedValue({ ok: true, started: true });
    bar();
    fireEvent.click(await screen.findByRole("button", { name: "Push" }));
    await waitFor(() => expect(api.plugin_scope_push).toHaveBeenCalledWith("brainrot-tcg"));
    fireEvent.click(screen.getByRole("button", { name: "Pull" }));
    await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("brainrot-tcg"));
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("updates waiting for a restart say who from, and Update now brings them in", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ head: 4, changes: { incoming: 2, incomingBy: ["Ana"], held: true } }));
    api.plugin_scope_pull?.mockResolvedValue({ ok: true });
    bar();
    expect(await screen.findByText("2 updates from Ana")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update now" }));
    await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("brainrot-tcg"));
  });

  it("a refused write is told through the alerts system and offers Ask to release", async () => {
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ pluginLabel: "Forge" }));
    api.plugin_scope_ask.mockResolvedValue({ ok: true });
    api.notify_activity.mockResolvedValue(true);
    bar("forge");
    await screen.findByRole("button", { name: "Details ▾" });
    push.handlers.forEach((fn) => fn({
      type: "plugin_write_refused", plugin_id: "forge", unit: "tree:scenes/ab12", unit_name: "MEGA_Duel_Stadium", holder: "Ana",
      since: new Date(2026, 9, 17, 15, 2).getTime() / 1000,
    }));
    const text = await screen.findByText(/^Forge: MEGA_Duel_Stadium is locked by Ana since .+\. Your change wasn't saved\.$/);
    expect(text).toBeTruthy();
    expect(api.notify_activity).toHaveBeenCalledWith(expect.objectContaining({ title: "Forge", phase: "error", detail: text.textContent }));
    expect(getBackgroundJobs()).toEqual([expect.objectContaining({ title: "Forge", phase: "error", detail: text.textContent })]);
    // Another plugin's refusal is not this bar's.
    push.handlers.forEach((fn) => fn({ type: "plugin_write_refused", plugin_id: "other", unit: "doc:x", holder: "Ben" }));

    fireEvent.click(screen.getByRole("button", { name: "Ask to release" }));
    await waitFor(() => expect(api.plugin_scope_ask).toHaveBeenCalledWith("forge", "tree:scenes/ab12"));
    expect(await screen.findByText("Asked Ana to release MEGA_Duel_Stadium.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Asked Ana to release MEGA_Duel_Stadium.")).toBeNull();
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
    expect(await screen.findByText("Alpha Studio's team data was reset on the server")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
    // Retry all, Retry and Drop wait for the choice: Retry all once uploaded the whole copy unasked.
    fireEvent.click(screen.getByRole("button", { name: "Details ▾" }));
    expect(screen.getAllByText("Refused: storage full").length).toBe(2);
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

  describe("plugins that keep their own folders", () => {
    const LOCAL = { kind: "personal", label: "Local", spaceId: "", readOnly: false };
    const URC = "Carried by this island's UEFN revision control";
    const NOTE = "This plugin's files are stored as it writes them on each member's PC; on the server and in transit they are encrypted.";
    /** The host's folder fields: the declared folders, the teams it offers Local into, the note. */
    const declared = (folders: Record<string, unknown>[] = [{ id: "scenes" }], offers: unknown[] = []) =>
      ({ teamFolders: folders, folderOffers: offers, folderNote: NOTE });
    const localStatus = (extra: Record<string, unknown> = {}) => ({
      ok: true, visible: true, pluginLabel: "Forge", canChange: true, state: "ok", ...declared(), binding: null,
      ...extra, scope: LOCAL,
    });
    const UNITS = [
      { folder: "scenes", unit: "MEGA_Duel_Stadium", name: "MEGA_Duel_Stadium", files: 12, bytes: 226 * 1024 ** 2 },
      { folder: "scenes", unit: "Arena", name: "Arena", files: 3, bytes: 2 * 1024 ** 2 },
    ];
    const chooseAlpha = async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Change ▾" }));
      fireEvent.click(await screen.findByRole("menuitemradio", { name: /Alpha Studio/ }));
      fireEvent.click(await screen.findByRole("button", { name: /^Switch/ }));
    };
    const choices = () => api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
      { id: "personal", kind: "personal", label: "Local" },
      { id: "s1", kind: "shared", label: "Alpha Studio" },
    ] });
    /** A call that answers when the test says so. */
    const pending = () => {
      let answer: (value: unknown) => void = () => {};
      api.plugin_scope_set.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
      return (value: unknown) => answer(value);
    };

    it("a switch says it is getting the team's files, reads how far it got, then asks which Local units to share", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus());
      choices();
      const answer = pending();
      bar("forge");
      expect(await screen.findByText("Only on this PC")).toBeTruthy();
      await chooseAlpha();
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("forge", "s1"));
      expect(await screen.findByText("Getting Alpha Studio's files…")).toBeTruthy();
      expect((screen.getByRole("button", { name: "Change ▾" }) as HTMLButtonElement).disabled).toBe(true);
      // The host notes its progress without telling the panel: the bar reads it while the switch runs.
      api.plugin_scope_status.mockResolvedValue(localStatus({ state: "binding", binding: { team: "Alpha Studio", pct: 40, at: 1 } }));
      expect(await screen.findByText("Getting Alpha Studio's files… 40%", undefined, { timeout: 3000 })).toBeTruthy();

      answer({ ok: false, needs: "first_share", team: "Alpha Studio", note: NOTE, units: UNITS });
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("Share Forge's files with Alpha Studio?")).toBeTruthy();
      expect(within(dialog).getByText(
        "Alpha Studio has none of Forge's files yet. Pick what to copy from your Local copy; the rest stays only on this PC.",
      )).toBeTruthy();
      expect(within(dialog).getByText(NOTE)).toBeTruthy();
      expect(within(dialog).getByText("12 files · 226 MB")).toBeTruthy();
      expect(within(dialog).getByText("2 of 2 picked · 228 MB")).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("checkbox", { name: /Arena/ }));
      expect(within(dialog).getByText("1 of 2 picked · 226 MB")).toBeTruthy();

      // The picked units go in: the bar says they are being sent, then shows the team's copy.
      api.plugin_scope_status.mockResolvedValue(localStatus());
      const sent = pending();
      fireEvent.click(within(dialog).getByRole("button", { name: "Copy and share" }));
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenLastCalledWith(
        "forge", "s1", { units: ["MEGA_Duel_Stadium"] }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(await screen.findByText("Sending your files to Alpha Studio…")).toBeTruthy();
      api.plugin_scope_status.mockResolvedValue(sharedStatus({ pluginLabel: "Forge", ...declared() }));
      sent({ ok: true });
      expect(await screen.findByText(/^Up to date/)).toBeTruthy();
    });

    it("picking nothing shares nothing until Start empty; Cancel changes nothing", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus());
      choices();
      api.plugin_scope_set.mockResolvedValueOnce({ ok: false, needs: "first_share", team: "Alpha Studio", units: UNITS.slice(1) });
      bar("forge");
      await chooseAlpha();
      const dialog = await screen.findByRole("dialog");
      // Without the host's note the dialog still says the files are stored as written on each PC.
      expect(within(dialog).getByText(NOTE)).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("checkbox", { name: /Arena/ }));
      expect((within(dialog).getByRole("button", { name: "Copy and share" }) as HTMLButtonElement).disabled).toBe(true);
      api.plugin_scope_set.mockResolvedValue({ ok: true });
      fireEvent.click(within(dialog).getByRole("button", { name: "Start empty" }));
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenLastCalledWith("forge", "s1", { start_empty: true }));

      api.plugin_scope_set.mockResolvedValueOnce({ ok: false, needs: "first_share", team: "Alpha Studio", units: [] });
      await chooseAlpha();
      const again = await screen.findByRole("dialog");
      expect(within(again).getByText("Your Local copy is empty.")).toBeTruthy();
      fireEvent.click(within(again).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(api.plugin_scope_set).toHaveBeenCalledTimes(3);
    });

    it("a failed pull fails the switch with the reason, and nothing changes", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus());
      choices();
      api.plugin_scope_set.mockResolvedValue({ ok: false, error: "Alpha Studio's files didn't arrive (offline). Nothing changed." });
      bar("forge");
      await chooseAlpha();
      expect(await screen.findByText("Alpha Studio's files didn't arrive (offline). Nothing changed.")).toBeTruthy();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(screen.getByText("Only on this PC")).toBeTruthy();
      expect((screen.getByRole("button", { name: "Change ▾" }) as HTMLButtonElement).disabled).toBe(false);
    });

    it("a folder that can't be shared from this PC says why and offers no team", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus(declared([{ id: "design", refused: URC }, { id: "noproject" }])));
      choices();
      bar("roguelike");
      expect(await screen.findByText(URC)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Change ▾" }));
      expect(await screen.findByRole("menuitemradio", { name: "Local" })).toBeTruthy();
      expect(screen.queryByRole("menuitemradio", { name: /Alpha Studio/ })).toBeNull();
      expect(screen.getAllByText(URC).length).toBe(2);
      cleanup();

      // Nothing else to share: no bar at all (Settings → Data says why).
      api.plugin_scope_status.mockResolvedValue(localStatus({ shareable: false, ...declared([{ id: "design", refused: URC }]) }));
      const { container } = bar("roguelike");
      await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
      expect(container.textContent).toBe("");
    });

    it("offers to copy Local into a team it was linked to before: the first share's picker", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus(declared(undefined, [{ space: "s1", label: "Alpha Studio" }])));
      api.plugin_scope_set.mockResolvedValueOnce({ ok: false, needs: "first_share", team: "Alpha Studio", units: UNITS });
      bar("forge");
      fireEvent.click(await screen.findByRole("button", { name: "Copy Local into Alpha Studio" }));
      // It asks which units even when the team has files already.
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("forge", "s1", { pick: true }));
      const dialog = await screen.findByRole("dialog");
      api.plugin_scope_set.mockResolvedValue({ ok: true });
      fireEvent.click(within(dialog).getByRole("button", { name: "Copy and share" }));
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenLastCalledWith(
        "forge", "s1", { units: ["MEGA_Duel_Stadium", "Arena"] }));
    });

    it("the offer, when the team already has the files, switches and says nothing was copied", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus(declared(undefined, [{ space: "s1", label: "Alpha Studio" }])));
      api.plugin_scope_set.mockResolvedValue({ ok: true });
      bar("forge");
      fireEvent.click(await screen.findByRole("button", { name: "Copy Local into Alpha Studio" }));
      expect(await screen.findByText(
        "Alpha Studio already has Forge's files, so nothing was copied. Your Local copy stays on this PC.",
      )).toBeTruthy();
      expect(screen.queryByRole("dialog")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      expect(screen.queryByText(/already has Forge's files/)).toBeNull();
    });

    it("on a team, offers to copy Local in for a project the team has no copy of, and names what it lacks", async () => {
      api.plugin_scope_status.mockResolvedValue(sharedStatus({
        pluginLabel: "Forge", ...declared(undefined, [{ space: "s1", label: "Alpha Studio" }]),
      }));
      api.plugin_scope_set.mockResolvedValueOnce({
        ok: false, needs: "first_share", team: "Alpha Studio", units: UNITS.slice(1), partial: true,
      });
      bar("forge");
      fireEvent.click(await screen.findByRole("button", { name: "Copy Local into Alpha Studio" }));
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("forge", "s1", { pick: true }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(
        "Alpha Studio has some of Forge's files already. Pick what else to copy from your Local copy; the rest stays only on this PC.",
      )).toBeTruthy();
      expect(within(dialog).getByRole("button", { name: "Copy nothing" })).toBeTruthy();
      api.plugin_scope_set.mockResolvedValue({ ok: true });
      fireEvent.click(within(dialog).getByRole("button", { name: "Copy and share" }));
      await waitFor(() => expect(api.plugin_scope_set).toHaveBeenLastCalledWith("forge", "s1", { units: ["Arena"] }));
    });

    it("no offer while a folder can't be shared from this PC", async () => {
      api.plugin_scope_status.mockResolvedValue(localStatus(declared([{ id: "design", refused: URC }], [{ space: "s1", label: "Alpha Studio" }])));
      bar("roguelike");
      expect(await screen.findByText(URC)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Copy Local into Alpha Studio" })).toBeNull();
    });

    it("on a team: a unit changed while someone holds it, and updates waiting behind Update now", async () => {
      api.plugin_scope_status.mockResolvedValue(sharedStatus({
        pluginLabel: "Forge", ...declared(),
        folders: [{ folder_id: "scenes", unit: "MEGA_Duel_Stadium", name: "MEGA_Duel_Stadium", state: "quarantined",
          reason: "Changed here while Ana holds it" }],
      }));
      bar("forge");
      expect(await screen.findByText("MEGA_Duel_Stadium: changed here while Ana holds it")).toBeTruthy();
      expect(line().getAttribute("title")).toBe(`Plugin data on each PC is encrypted for the signed-in account. ${NOTE}`);
      cleanup();

      api.plugin_scope_status.mockResolvedValue(sharedStatus({
        pluginLabel: "Forge", ...declared(), head: 9,
        changes: { incoming: 2, incomingBy: ["Ana"], held: true },
      }));
      api.plugin_scope_pull?.mockResolvedValue({ ok: true });
      const changed = vi.fn();
      render(
        <ConfirmModalProvider>
          <PluginScopeBar pluginId="forge" onScopeChanged={changed} />
        </ConfirmModalProvider>,
      );
      expect(await screen.findByText("2 updates from Ana")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Update now" }));
      await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("forge"));
      // The panel re-reads its data once the updates are in.
      await waitFor(() => expect(changed).toHaveBeenCalled());
    });
  });

  it("after a reset, without the host call, says so and offers no choice", async () => {
    api.space_reset_settle = undefined;
    api.plugin_scope_status.mockResolvedValue(sharedStatus({ state: "reset", kindLabel: "Team" }, { readOnly: true }));
    bar();
    expect(await screen.findByText("Alpha Studio's team data was reset on the server")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Upload my copy" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear my copy" })).toBeNull();
  });
});
