// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import type { PluginScopeStatus } from "../types/panel";
import { PluginScopeDrawer } from "./PluginScopeDrawer";

const api = vi.hoisted(() => ({
  plugin_scope_activity: vi.fn() as ReturnType<typeof vi.fn> | undefined,
  plugin_scope_sync: vi.fn(),
  plugin_scope_retry: vi.fn(),
  plugin_scope_drop: vi.fn(),
  plugin_scope_lock: vi.fn(),
  plugin_scope_unlock: vi.fn(),
  plugin_scope_break: vi.fn(),
  plugin_scope_ask: vi.fn(),
  plugin_scope_resolve: vi.fn(),
  plugin_scope_restore: vi.fn(),
  plugin_scope_history: vi.fn(),
  plugin_scope_mode: vi.fn(),
  plugin_scope_push: vi.fn(),
  plugin_scope_pull: vi.fn(),
  plugin_scope_save_unsent: vi.fn(),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));

const activity = api.plugin_scope_activity;
const onChanged = vi.fn();
beforeEach(() => {
  for (const fn of Object.values(api)) fn?.mockResolvedValue({ ok: true });
  api.plugin_scope_activity?.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  api.plugin_scope_activity = activity;
});

const status = (extra: PluginScopeStatus = {}): PluginScopeStatus => ({
  ok: true, visible: true, pluginLabel: "Forge", state: "ok", pending: 0, head: 12, mode: "auto",
  people: [], locks: [], ...extra,
  scope: { kind: "shared", label: "Alpha", spaceId: "s1", readOnly: false, ...extra.scope },
});

const drawer = (s: PluginScopeStatus) =>
  render(
    <ConfirmModalProvider>
      <PluginScopeDrawer pluginId="forge" status={s} onChanged={onChanged} />
    </ConfirmModalProvider>,
  );

/** The confirm modal's main button ("Break lock (B)"). */
const confirmButton = (label: string) => screen.getByRole("button", { name: new RegExp(`^${label} \\(`) });

describe("plugin scope drawer", () => {
  it("lists who else is here and what they are doing, never this PC", async () => {
    drawer(status({
      people: [
        { user_name: "Ana", device: "ANA-PC", plugins: { forge: { editing: [{ unitName: "MEGA_Duel_Stadium", actor: "user" }] } } },
        { user_name: "Ben", device: "BEN-PC", plugins: { forge: { editing: [{ unitName: "Arena", actor: "agent", ducky: "Builder" }] } } },
        { user_name: "Cy", device: "CY-PC", plugins: { forge: { viewing: true } } },
        { user_name: "Me", me: true, plugins: { forge: { viewing: true } } },
      ],
    }));
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows).toEqual([
      "AnaANA-PCEditing MEGA_Duel_Stadium",
      "BenBEN-PCDucky Builder editing Arena",
      "CyCY-PCViewing",
    ]);
    await waitFor(() => expect(api.plugin_scope_activity).toHaveBeenCalledWith("forge"));
  });

  it("has the space looked at once when it opens, never on each new status (each look is a round)", async () => {
    const view = drawer(status());
    expect(screen.getByText("Nothing is locked.")).toBeTruthy();
    await waitFor(() => expect(api.plugin_scope_activity).toHaveBeenCalledTimes(1));
    // The round's news comes back as a fresher status from the bar.
    view.rerender(
      <ConfirmModalProvider>
        <PluginScopeDrawer pluginId="forge" status={status({ locks: [{ unit: "doc:deck", name: "deck", holder: "Ana" }] })}
          onChanged={onChanged} />
      </ConfirmModalProvider>,
    );
    expect(screen.getByRole("button", { name: "Ask Ana to release deck" })).toBeTruthy();
    expect(api.plugin_scope_activity).toHaveBeenCalledTimes(1);

    // Without the call the drawer still shows the status.
    view.unmount();
    api.plugin_scope_activity = undefined;
    drawer(status());
    expect(screen.getByText("Nothing is locked.")).toBeTruthy();
  });

  it("locks: Release mine, Ask to release, and Break only after its confirm", async () => {
    drawer(status({
      locks: [
        { unit: "tree:scenes/ab12", name: "MEGA_Duel_Stadium", holder: "Ana", since: 1_800_000_000, leaseLeft: 240 },
        { unit: "doc:pack", name: "pack", mine: true, leaseLeft: 0 },
      ],
    }));
    expect(screen.getByText("4 min")).toBeTruthy();
    expect(screen.getByText("Ran out")).toBeTruthy();
    expect(screen.getByText("You")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Release pack" }));
    await waitFor(() => expect(api.plugin_scope_unlock).toHaveBeenCalledWith("forge", "doc:pack"));

    fireEvent.click(screen.getByRole("button", { name: "Ask Ana to release MEGA_Duel_Stadium" }));
    await waitFor(() => expect(api.plugin_scope_ask).toHaveBeenCalledWith("forge", "tree:scenes/ab12"));
    expect(await screen.findByText("Asked Ana to release MEGA_Duel_Stadium.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Break Ana's lock on MEGA_Duel_Stadium" }));
    expect(await screen.findByText("Break Ana's lock on MEGA_Duel_Stadium?")).toBeTruthy();
    expect(screen.getByText(
      "Ana is told, and what Ana changed in MEGA_Duel_Stadium and hasn't sent yet becomes a conflict on their PC. Nothing of theirs is lost.",
    )).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Cancel/ }));
    await waitFor(() => expect(screen.queryByText("Break Ana's lock on MEGA_Duel_Stadium?")).toBeNull());
    expect(api.plugin_scope_break).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Break Ana's lock on MEGA_Duel_Stadium" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Break lock \(/ }));
    await waitFor(() => expect(api.plugin_scope_break).toHaveBeenCalledWith("forge", "tree:scenes/ab12"));
    expect(onChanged).toHaveBeenCalled();
  });

  it("a refused lock action says why in the drawer", async () => {
    api.plugin_scope_break.mockResolvedValue({ ok: false, error: "Only owners and admins can break a live lock." });
    drawer(status({ locks: [{ unit: "doc:deck", name: "deck", holder: "Ana" }] }));
    fireEvent.click(screen.getByRole("button", { name: "Break Ana's lock on deck" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Break lock \(/ }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Only owners and admins can break a live lock.")).toBeTruthy();
  });

  it("changes: Retry sends again, Retry all, Drop asks first, blocked incoming Re-download", async () => {
    drawer(status({
      changes: {
        outgoing: [
          { kind: "asset", key: "art/big.png", state: "refused", reason: "too big for your plan", size: 3 * 1024 ** 2 },
          { kind: "doc", key: "scene_1", state: "blocked", attempts: 5, reason: "file in use" },
          { kind: "doc", key: "deck", state: "locked_out", reason: "Locked by Ana" },
          { kind: "doc", key: "pack", state: "queued" },
        ],
        incoming: 2, incomingBy: ["Ana"],
        blocked: [{ kind: "asset", key: "art/sky.png", error: "a chunk failed its check", attempts: 2 }],
      },
    }));
    expect(screen.getByText("Refused: too big for your plan")).toBeTruthy();
    expect(screen.getByText("Couldn't be sent after 5 tries: file in use")).toBeTruthy();
    expect(screen.getByText("Locked by Ana")).toBeTruthy();
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.getByText("3 MB")).toBeTruthy();
    expect(screen.getByText("2 incoming from Ana")).toBeTruthy();
    // Locked out and queued changes have no Retry or Drop.
    expect(screen.queryByRole("button", { name: "Retry deck" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Drop my change to pack" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry scene_1" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenCalledWith("forge", "scene_1"));
    await waitFor(() => expect(api.plugin_scope_sync).toHaveBeenCalledWith("forge", true));

    fireEvent.click(screen.getByRole("button", { name: "Retry all" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenLastCalledWith("forge"));

    fireEvent.click(screen.getByRole("button", { name: "Drop my change to art/big.png" }));
    expect(await screen.findByText("Drop your change to art/big.png?")).toBeTruthy();
    expect(api.plugin_scope_drop).not.toHaveBeenCalled();
    fireEvent.click(confirmButton("Drop my change"));
    await waitFor(() => expect(api.plugin_scope_drop).toHaveBeenCalledWith("forge", "asset", "art/big.png"));
    expect(onChanged).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole("button", { name: "Re-download art/sky.png" }));
    await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("forge", "asset", "art/sky.png"));
  });

  it("changes a provider held back (no engine list) show with their reasons", () => {
    drawer(status({
      head: undefined, mode: undefined, people: undefined, locks: undefined, refused: 3,
      items: [{ kind: "doc", key: "a", state: "refused", reason: "storage full" }],
    }));
    expect(screen.getByText("Refused: storage full")).toBeTruthy();
    expect(screen.getByText("2 more not listed")).toBeTruthy();
    // No engine: no People, Locks, History or Mode.
    expect(screen.queryByText("People")).toBeNull();
    expect(screen.queryByText("Locks")).toBeNull();
    expect(screen.queryByText("History")).toBeNull();
    expect(screen.queryByText("Mode")).toBeNull();
  });

  it("a copy on the older sync shows its changes and conflicts, never History or Mode", () => {
    drawer(status({
      engine: "v1", head: 0, mode: "auto", people: undefined, locks: undefined,
      changes: { outgoing: [{ kind: "doc", key: "deck", state: "queued" }] },
      conflicts: [{ kind: "doc", key: "pack", by: "Ben", reason: "changed" }],
    }));
    expect(screen.getByText("deck")).toBeTruthy();
    expect(screen.getByText("Conflicts")).toBeTruthy();
    expect(screen.queryByText("History")).toBeNull();
    expect(screen.queryByText("Mode")).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Sync mode" })).toBeNull();
  });

  it("conflicts: Keep mine, Keep theirs after a confirm, Keep both for folders, Compare", async () => {
    api.plugin_scope_resolve.mockImplementation(async (_p: string, _k: string, _key: string, choice: string) =>
      choice === "compare" ? { ok: true, diff: "- hp: 10\n+ hp: 12" } : { ok: true });
    drawer(status({
      conflicts: [
        { kind: "doc", key: "deck", by: "Ana", reason: "edit" },
        { kind: "doc", key: "pack", by: "Ben", reason: "deleted" },
        { kind: "tree", key: "tree:scenes/ab12", name: "MEGA_Duel_Stadium", by: "Ana" },
      ],
    }));
    expect(screen.getAllByText(/^Changed here and by Ana/).length).toBe(2);
    expect(screen.getByText(/^Ben deleted this; you changed it/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Keep both: deck" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Keep mine: deck" }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith("forge", "doc", "deck", "mine"));
    expect(onChanged).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole("button", { name: "Accept delete: pack" }));
    expect(await screen.findByText("Keep Ben's version of pack?")).toBeTruthy();
    fireEvent.click(confirmButton("Keep theirs"));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith("forge", "doc", "pack", "theirs"));
    expect(screen.getByRole("button", { name: "Restore mine: pack" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Keep both: MEGA_Duel_Stadium" }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith("forge", "tree", "tree:scenes/ab12", "both"));

    fireEvent.click(screen.getByRole("button", { name: "Compare: deck" }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith("forge", "doc", "deck", "compare"));
    expect((await screen.findByText(/- hp: 10/)).textContent).toBe("- hp: 10\n+ hp: 12");
    expect(screen.getByRole("button", { name: "Compare: deck" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("history: Undo, Restore to here and Restore item, each confirmed in a modal", async () => {
    api.plugin_scope_history.mockImplementation(async (_p: string, req: { key?: string; before?: number }) => req?.key
      ? { ok: true, entries: [{ seq: 9, by: "Ana", at: 1_800_000_000, kind: "doc", key: "deck", size: 2048 }] }
      : req?.before ? { ok: true, more: false, entries: [{ seq: 10, by: "Cy", count: 1 }] }
      : { ok: true, more: true, entries: [
        { seq: 12, by: "Ben", actor: "agent", ducky: "Builder", device: "BEN-PC", message: "Balance pass", count: 2,
          items: [["doc", "deck"], ["doc", "pack"]] },
        { seq: 11, by: "Ana", count: 1 },
      ] });
    api.plugin_scope_restore.mockResolvedValue({ ok: true, seq: 13, skipped: [["doc", "pack"]] });
    drawer(status());
    fireEvent.click(screen.getByRole("button", { name: "Show history" }));
    await waitFor(() => expect(api.plugin_scope_history).toHaveBeenCalledWith("forge", { before: undefined, limit: 20 }));
    expect(await screen.findByText("Ben's ducky Builder")).toBeTruthy();
    expect(screen.getByText("Balance pass")).toBeTruthy();
    expect(screen.getByText("BEN-PC")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Undo #12" }));
    expect(await screen.findByText("Undo change #12?")).toBeTruthy();
    expect(screen.getByText(/It is a new change everyone in Alpha gets; the history stays as it is\.$/)).toBeTruthy();
    expect(api.plugin_scope_restore).not.toHaveBeenCalled();
    fireEvent.click(confirmButton("Undo"));
    await waitFor(() => expect(api.plugin_scope_restore).toHaveBeenCalledWith("forge", { undoSeq: 12 }));
    expect(await screen.findByText("Restored. 1 item wasn't: its version is no longer kept.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Restore to #11" }));
    expect(await screen.findByText("Restore Forge to #11?")).toBeTruthy();
    fireEvent.click(confirmButton("Restore"));
    await waitFor(() => expect(api.plugin_scope_restore).toHaveBeenLastCalledWith("forge", { toSeq: 11 }));

    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => expect(api.plugin_scope_history).toHaveBeenCalledWith("forge", { before: 11, limit: 20 }));

    fireEvent.click(screen.getAllByRole("button", { name: "2" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Versions of deck" }));
    await waitFor(() => expect(api.plugin_scope_history).toHaveBeenCalledWith("forge", { kind: "doc", key: "deck", limit: 20 }));
    expect(await screen.findByText("Versions of deck")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore deck to #9" }));
    expect(await screen.findByText("Restore deck to #9?")).toBeTruthy();
    fireEvent.click(confirmButton("Restore"));
    await waitFor(() => expect(api.plugin_scope_restore).toHaveBeenLastCalledWith("forge", { items: [{ kind: "doc", key: "deck", seq: 9 }] }));
    fireEvent.click(screen.getByRole("button", { name: "Back to history" }));
    expect(await screen.findByRole("button", { name: "Undo #12" })).toBeTruthy();
  });

  it("folder units show only when the plugin declares folders; Lock and Release", async () => {
    const view = drawer(status());
    expect(screen.queryByText("Folder units")).toBeNull();
    view.unmount();
    drawer(status({
      folders: [
        { unit: "tree:scenes/1", name: "MEGA_Duel_Stadium", state: "changed" },
        { unit: "tree:scenes/2", name: "Arena", state: "locked", holder: "Ana" },
        { unit: "tree:scenes/3", name: "Lobby", state: "locked", mine: true },
        { unit: "tree:scenes/4", name: "Vault", state: "ok" },
      ],
    }));
    expect(screen.getByText("Folder units")).toBeTruthy();
    expect(screen.getByText("Changed here")).toBeTruthy();
    expect(screen.getByText("Locked by Ana")).toBeTruthy();
    expect(screen.getByText("Locked by you")).toBeTruthy();
    expect(screen.getByText("Up to date")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Lock Arena" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Lock Vault" }));
    await waitFor(() => expect(api.plugin_scope_lock).toHaveBeenCalledWith("forge", "tree:scenes/4", "Vault"));
    fireEvent.click(screen.getByRole("button", { name: "Release Lobby" }));
    await waitFor(() => expect(api.plugin_scope_unlock).toHaveBeenCalledWith("forge", "tree:scenes/3"));
  });

  it("mode: Auto or Manual; Manual pushes with an optional message and pulls", async () => {
    const view = drawer(status());
    expect(screen.getByRole("radio", { name: "Auto" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByRole("button", { name: "Push" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Manual" }));
    await waitFor(() => expect(api.plugin_scope_mode).toHaveBeenCalledWith("forge", "manual"));
    view.unmount();

    drawer(status({ mode: "manual" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Push message (optional)" }), { target: { value: "  New arena  " } });
    fireEvent.click(screen.getByRole("button", { name: "Push" }));
    await waitFor(() => expect(api.plugin_scope_push).toHaveBeenCalledWith("forge", "New arena"));
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe(""));
    fireEvent.click(screen.getByRole("button", { name: "Pull" }));
    await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("forge"));
    fireEvent.click(screen.getByRole("radio", { name: "Auto" }));
    await waitFor(() => expect(api.plugin_scope_mode).toHaveBeenLastCalledWith("forge", "auto"));
  });

  it("a lost space offers Save my unsent changes to Local until the person has chosen", async () => {
    api.plugin_scope_save_unsent.mockResolvedValue({ ok: true, saved: [
      { plugin: "forge", kind: "doc", key: "deck", localKey: "deck-from-alpha" },
      { plugin: "forge", kind: "doc", key: "pack", localKey: "pack" },
    ] });
    const view = drawer(status({ state: "lost", unsent: 2 }));
    expect(screen.getByText(/^2 changes made here never reached Alpha\./)).toBeTruthy();
    expect(screen.queryByText("Changes")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save my unsent changes to Local" }));
    await waitFor(() => expect(api.plugin_scope_save_unsent).toHaveBeenCalledWith("forge", "save"));
    expect(await screen.findByText("Saved 2 changes to Local.")).toBeTruthy();

    // Or let them go, after a confirm.
    fireEvent.click(screen.getByRole("button", { name: "Let them go" }));
    expect(await screen.findByText("They are never sent, and they leave this PC with Alpha's copy.")).toBeTruthy();
    fireEvent.click(confirmButton("Let them go"));
    await waitFor(() => expect(api.plugin_scope_save_unsent).toHaveBeenLastCalledWith("forge", "discard"));
    view.unmount();

    drawer(status({ state: "lost", unsent: 2, unsentChosen: true }));
    expect(screen.queryByRole("button", { name: "Save my unsent changes to Local" })).toBeNull();
  });
});
