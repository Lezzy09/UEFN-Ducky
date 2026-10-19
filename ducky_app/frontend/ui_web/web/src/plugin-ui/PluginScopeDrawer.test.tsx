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

const NOTE = "This plugin's files are stored as it writes them on each member's PC; on the server and in transit they are encrypted.";
const URC = "Carried by this island's UEFN revision control";

/** The confirm modal's main button ("Break lock (B)"). */
const confirmButton = (label: string) => screen.getByRole("button", { name: new RegExp(`^${label} \\(`) });

describe("plugin scope drawer", () => {
  it("lists everyone in the space, one row each: you first, then who edits, views, the rest", async () => {
    drawer(status({
      people: [
        { user_name: "Dee", device: "DEE-PC", plugins: { other: { viewing: true } } },
        { user_name: "Cy", device: "CY-PC", plugins: { forge: { viewing: true } } },
        { user_name: "Ana", device: "ANA-PC", plugins: { forge: { editing: [
          { unitName: "MEGA_Duel_Stadium", actor: "user" }, { unitName: "Crate", actor: "user" },
        ] } } },
        { user_name: "Ben", device: "BEN-PC", plugins: { forge: { editing: [{ unitName: "Arena", actor: "agent", ducky: "Builder" }] } } },
        { user_name: "Me", me: true, device: "MainPC", plugins: { forge: { viewing: true } } },
      ],
    }));
    expect(screen.getByText("People in Alpha")).toBeTruthy();
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Member", "PC", "In Forge", "Since"]);
    const rows = within(table).getAllByRole("row").slice(1).map((r) => r.textContent);
    // Each name follows its avatar's initials.
    expect(rows).toEqual([
      "MYou (Me)MainPCViewing",
      "AAnaANA-PCEditing MEGA_Duel_Stadium and Crate",
      "BBenBEN-PCAI (their ducky Builder) is editing Arena",
      "CCyCY-PCViewing",
      "DDeeDEE-PCNot in Forge",
    ]);
    expect(screen.queryByText("Nobody else is here right now.")).toBeNull();
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
    expect(await screen.findByText("AI (Ben's ducky Builder)")).toBeTruthy();
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

  it("history: the move to the new sync (#1) can be restored to but not undone", async () => {
    api.plugin_scope_history.mockResolvedValue({ ok: true, more: false, entries: [
      { seq: 2, by: "Ana", count: 1 },
      { seq: 1, by: "Imported from team data", count: 40 },
    ] });
    drawer(status());
    fireEvent.click(screen.getByRole("button", { name: "Show history" }));
    expect(await screen.findByRole("button", { name: "Undo #2" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Undo #1" })).toBeNull();
    expect(screen.getByRole("button", { name: "Restore to #1" })).toBeTruthy();
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

  it("the folder units table: size, each state, and the plaintext note in the help", () => {
    drawer(status({
      teamFolders: [{ id: "scenes" }], folderNote: NOTE,
      folders: [
        { folder_id: "scenes", unit: "MEGA_Duel_Stadium", name: "MEGA_Duel_Stadium", state: "up_to_date", files: 12, bytes: 226 * 1024 ** 2 },
        { folder_id: "scenes", unit: "Arena", name: "Arena", state: "conflict", files: 3, bytes: 2048 },
        { folder_id: "scenes", unit: "Lobby", name: "Lobby", state: "refused", files: 2, bytes: 10,
          reason: "Lobby.json and lobby.json differ only by upper/lower case or accents. Rename one so the team can tell them apart." },
      ],
    }));
    const table = screen.getByText("Folder units").parentElement as HTMLElement;
    const rows = within(table).getAllByRole("row").slice(1).map((r) => [...r.querySelectorAll("td")].slice(0, 3).map((td) => td.textContent));
    expect(rows).toEqual([
      ["MEGA_Duel_Stadium", "12 files · 226 MB", "Up to date"],
      ["Arena", "3 files · 2 KB", "Changed here and by someone else"],
      ["Lobby", "2 files · 10 B",
        "Lobby.json and lobby.json differ only by upper/lower case or accents. Rename one so the team can tell them apart."],
    ]);
    // A refused unit can't be locked; the others can.
    expect(screen.queryByRole("button", { name: "Lock Lobby" })).toBeNull();
    expect(screen.getByRole("button", { name: "Lock Arena" })).toBeTruthy();
    expect(screen.getByText(NOTE)).toBeTruthy();
  });

  it("says why a declared folder can't be shared from this PC", () => {
    drawer(status({ teamFolders: [{ id: "design", refused: URC }, { id: "noproject" }] }));
    expect(screen.getByText("Folder units")).toBeTruthy();
    expect(screen.getByText(URC)).toBeTruthy();
    // The plaintext note says what the help says even without the host's words.
    expect(screen.getByText(NOTE)).toBeTruthy();
    cleanup();
    drawer(status({ teamFolders: [
      { id: "design", refused: URC },
      { id: "noproject", refused: "This folder is synced by OneDrive. Move it out of OneDrive to share it with a team." },
    ] }));
    expect(screen.getByText(`design: ${URC}`)).toBeTruthy();
    expect(screen.getByText("noproject: This folder is synced by OneDrive. Move it out of OneDrive to share it with a team.")).toBeTruthy();
  });

  it("a unit changed while someone else holds it: Ask to release, Keep mine as a copy, Discard mine after a confirm", async () => {
    drawer(status({
      folders: [{ folder_id: "scenes", unit: "MEGA_Duel_Stadium", name: "MEGA_Duel_Stadium", state: "quarantined",
        reason: "Changed here while Ana holds it" }],
    }));
    expect(screen.getByText("Changed here while Ana holds it")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Lock MEGA_Duel_Stadium" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ask the holder to release MEGA_Duel_Stadium" }));
    await waitFor(() => expect(api.plugin_scope_ask).toHaveBeenCalledWith("forge", "scenes/MEGA_Duel_Stadium"));

    fireEvent.click(screen.getByRole("button", { name: "Keep mine as a copy: MEGA_Duel_Stadium" }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith(
      "forge", "tree", "scenes/MEGA_Duel_Stadium", "keep_copy"));
    expect(await screen.findByText(
      "Your version of MEGA_Duel_Stadium is kept beside it as a copy; MEGA_Duel_Stadium has Alpha's version again.")).toBeTruthy();
    expect(onChanged).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole("button", { name: "Discard mine: MEGA_Duel_Stadium" }));
    expect(await screen.findByText("Discard your changes to MEGA_Duel_Stadium?")).toBeTruthy();
    expect(screen.getByText("MEGA_Duel_Stadium goes back to Alpha's version. What you changed here is not kept.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Cancel/ }));
    await waitFor(() => expect(screen.queryByText("Discard your changes to MEGA_Duel_Stadium?")).toBeNull());
    expect(api.plugin_scope_resolve).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Discard mine: MEGA_Duel_Stadium" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Discard mine \(/ }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenLastCalledWith(
      "forge", "tree", "scenes/MEGA_Duel_Stadium", "discard"));
  });

  it("a {PROJECT} folder's unit goes by its folder and project id; a refusal from the host stays in the drawer", async () => {
    api.plugin_scope_resolve.mockResolvedValueOnce({ ok: false, error: "MEGA_Duel_Stadium is open in another program." });
    drawer(status({
      folders: [{ folder_id: "design", unit: "1f0c-guid", name: "design", state: "quarantined", holder: "Ben" }],
    }));
    expect(screen.getByText("Changed here while Ben holds it")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep mine as a copy: design" }));
    await waitFor(() => expect(api.plugin_scope_resolve).toHaveBeenCalledWith("forge", "tree", "design/1f0c-guid", "keep_copy"));
    expect((await screen.findByRole("alert")).textContent).toBe("MEGA_Duel_Stadium is open in another program.");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("without the host's call, a held unit offers no Keep or Discard", () => {
    const saved = api.plugin_scope_resolve;
    Object.assign(api, { plugin_scope_resolve: undefined });
    try {
      drawer(status({ folders: [{ folder_id: "scenes", unit: "Arena", name: "Arena", state: "quarantined" }] }));
      expect(screen.getByText("Changed here while someone else holds it")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Keep mine as a copy: Arena" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Discard mine: Arena" })).toBeNull();
    } finally {
      Object.assign(api, { plugin_scope_resolve: saved });
    }
  });

  it("the host's unit states; Lock and Release go by the unit's lock id, else <folder>/<unit>", async () => {
    drawer(status({
      locks: [{ unit: "tree:scenes/9f2c", name: "Lobby", mine: true }],
      folders: [
        { folder_id: "scenes", unit: "Arena", unitId: "tree:scenes/ab12", name: "Arena", state: "up_to_date" },
        { folder_id: "scenes", unit: "Vault", name: "Vault", state: "changed_here" },
        { folder_id: "scenes", unit: "Lobby", unitId: "tree:scenes/9f2c", name: "Lobby", state: "up_to_date", mine: true },
        { folder_id: "scenes", unit: "Dock", unitId: "tree:scenes/77d0", name: "Dock", state: "locked_by", holder: "Ana" },
        { folder_id: "scenes", unit: "Pier", unitId: "tree:scenes/5e1a", name: "Pier", state: "incoming" },
      ],
    }));
    const table = screen.getByText("Folder units").parentElement as HTMLElement;
    const states = within(table).getAllByRole("row").slice(1).map((r) => r.querySelectorAll("td")[2].textContent);
    expect(states).toEqual(["Up to date", "Changed here", "Up to date", "Locked by Ana", "Update waiting"]);
    expect(screen.queryByRole("button", { name: "Lock Dock" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Lock Arena" }));
    await waitFor(() => expect(api.plugin_scope_lock).toHaveBeenCalledWith("forge", "tree:scenes/ab12", "Arena"));
    fireEvent.click(screen.getByRole("button", { name: "Lock Vault" }));
    await waitFor(() => expect(api.plugin_scope_lock).toHaveBeenLastCalledWith("forge", "scenes/Vault", "Vault"));
    // This PC holds Lobby: Release, never Lock.
    expect(within(table).queryByRole("button", { name: "Lock Lobby" })).toBeNull();
    fireEvent.click(within(table).getByRole("button", { name: "Release Lobby" }));
    await waitFor(() => expect(api.plugin_scope_unlock).toHaveBeenCalledWith("forge", "tree:scenes/9f2c"));
  });

  it("a folder unit's outgoing change shows its file count and why it is held, without Retry or Drop", () => {
    drawer(status({
      changes: { outgoing: [
        { kind: "tree", key: "scenes/Arena", folder_id: "scenes", unit: "Arena", name: "Arena", files: 3, state: "quarantined",
          reason: "Changed here while Ana holds it" },
        { kind: "tree", key: "scenes/Vault", folder_id: "scenes", unit: "Vault", name: "Vault", files: 1, state: "queued" },
        { kind: "tree", key: "scenes/Lobby", folder_id: "scenes", unit: "Lobby", name: "Lobby", files: 2, state: "refused",
          reason: "Lobby.json and lobby.json differ only by upper/lower case or accents. Rename one." },
      ] },
    }));
    const rows = within(screen.getByText("Changes").parentElement as HTMLElement).getAllByRole("row").slice(1)
      .map((r) => [...r.querySelectorAll("td")].slice(0, 3).map((td) => td.textContent));
    expect(rows).toEqual([
      ["Arena", "3 files", "Changed here while Ana holds it"],
      ["Vault", "1 file", "Queued"],
      ["Lobby", "2 files", "Refused: Lobby.json and lobby.json differ only by upper/lower case or accents. Rename one."],
    ]);
    // Renaming fixes a name clash: Retry and Drop my change are for data items.
    expect(screen.queryByRole("button", { name: "Retry Lobby" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Drop my change to Lobby" })).toBeNull();
  });

  it("a folder unit the server kept failing has Retry (and Retry all), never Drop my change", async () => {
    drawer(status({
      changes: { outgoing: [
        { kind: "tree", key: "scenes/Arena", folder_id: "scenes", unit: "Arena", name: "Arena", files: 2, state: "blocked",
          reason: "bad request" },
        { kind: "tree", key: "scenes/Vault", folder_id: "scenes", unit: "Vault", name: "Vault", files: 1, state: "blocked",
          reason: "bad request" },
      ] },
    }));
    expect(screen.getAllByText("Couldn't be sent: bad request")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Drop my change to Arena" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry Arena" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenCalledWith("forge", "scenes/Arena"));
    fireEvent.click(screen.getByRole("button", { name: "Retry all" }));
    await waitFor(() => expect(api.plugin_scope_retry).toHaveBeenLastCalledWith("forge"));
  });

  it("updates held for a restart wait for Update now, which brings them in", async () => {
    const view = drawer(status({ changes: { incoming: 2, incomingBy: ["Ana", "Ben"], held: true } }));
    expect(screen.getByText("2 incoming from Ana and Ben · they wait until you update")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update now" }));
    await waitFor(() => expect(api.plugin_scope_pull).toHaveBeenCalledWith("forge"));
    expect(onChanged).toHaveBeenLastCalledWith(true);
    view.unmount();
    // Changes that apply by themselves need no button.
    drawer(status({ changes: { incoming: 1, incomingBy: ["Ana"], held: false } }));
    expect(screen.getByText("1 incoming from Ana")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update now" })).toBeNull();
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
