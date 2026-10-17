import { describe, expect, it } from "vitest";
import type { PluginScopeStatus } from "../types/panel";
import {
  breakConfirm,
  clockText,
  conflictText,
  doingText,
  dropConfirm,
  durationText,
  listText,
  locksText,
  lostText,
  notShared,
  outgoingStateText,
  peopleRows,
  peopleText,
  refusedWriteText,
  resetConfirm,
  resetText,
  restoreConfirm,
  sentText,
  statusPhrase,
  storageLine,
  switchConfirm,
  syncText,
  unavailableText,
} from "./scopeBarText";

const GB = 1024 ** 3;
const NOW = 1_000_000_000_000;

/** A shared copy that is up to date, with `extra` on top. */
const shared = (extra: PluginScopeStatus = {}): PluginScopeStatus => ({
  visible: true, state: "ok", pending: 0, head: 482, syncedAt: NOW / 1000 - 120, kindLabel: "Team",
  scope: { kind: "shared", label: "Alpha", spaceId: "s1", readOnly: false }, ...extra,
});
const ANA_LOCK = { unit: "tree:f/1", name: "MEGA_Duel_Stadium", holder: "Ana", since: 0, leaseLeft: 240 };

describe("scope bar text", () => {
  it("warns from 80%, says full at the limit, and names the level in text", () => {
    expect(storageLine({ usedBytes: 34 * 1024 ** 2, limitBytes: 5 * GB })).toMatchObject({
      text: "34 MB of 5 GB",
      level: "ok",
      note: "",
    });
    expect(storageLine({ usedBytes: 4 * GB, limitBytes: 5 * GB })).toMatchObject({ level: "warn", note: "80% used" });
    expect(storageLine({ usedBytes: 5 * GB, limitBytes: 5 * GB })).toMatchObject({ level: "full", note: "Storage full" });
    expect(storageLine({ usedBytes: 1 })).toBeNull();
  });

  it("says when it synced, what is queued, and the switch warning", () => {
    expect(syncText({ syncedAt: 100, pending: 0, state: "ok" }, 105_000)).toBe("Synced 5 s ago");
    expect(syncText({ syncedAt: 100, pending: 3, state: "offline" }, 105_000)).toBe("Offline · 3 changes waiting");
    expect(switchConfirm("BrainRot TCG", { kind: "shared", label: "Alpha Studio" })).toEqual({
      title: "Switch BrainRot TCG to Alpha Studio data?",
      message: "Nothing is copied. BrainRot TCG restarts with Alpha Studio's data.",
    });
    expect(switchConfirm("BrainRot TCG", { kind: "personal", label: "Local" })).toEqual({
      title: "Switch BrainRot TCG to Local data?",
      message: "Nothing is copied. BrainRot TCG restarts with its Local data.",
    });
  });

  it("says a lost space's copy is locked and when it leaves this PC", () => {
    const at = new Date(2026, 9, 15, 12).getTime() / 1000;
    expect(lostText("Alpha Studio", at, "en-US")).toBe(
      "You no longer have access to Alpha Studio. Its data here is locked and leaves this PC on October 15 unless access comes back.",
    );
    expect(lostText("Alpha Studio")).toBe("You no longer have access to Alpha Studio. Its data here is locked until access comes back.");
  });

  it("names why nothing syncs: no provider, unavailable, reset", () => {
    const noProvider = { state: "no_provider", pending: 2, error: "Not connected: Ducky Account isn't running" };
    expect(syncText(noProvider, 0)).toBe("Not connected: Ducky Account isn't running · 2 changes waiting");
    expect(syncText({ state: "no_provider", pending: 1 }, 0)).toBe("Not connected · 1 change waiting");
    expect(syncText({ state: "unavailable", error: "permission denied" }, 0)).toBe("Not available: permission denied");
    expect(syncText({ state: "unavailable" }, 0)).toBe("Not available");
    expect(syncText({ state: "reset", syncedAt: 100 }, 105_000)).toBe("Reset on the server");

    expect(unavailableText("Alpha Studio", "permission denied: uefn-ducky-store.teams")).toBe(
      "Alpha Studio isn't available right now (permission denied: uefn-ducky-store.teams). Read-only until it's back.",
    );
    expect(unavailableText("Alpha Studio")).toBe("Alpha Studio isn't available right now. Read-only until it's back.");
    expect(resetText("Alpha", "team", true)).toBe(
      "Alpha's team data was reset on the server. Your copy here is read-only until you choose what to do with it.",
    );
    expect(resetText("Alpha", "team", false)).toBe("Alpha's team data was reset on the server. Your copy here is read-only.");
  });

  it("lists each change that isn't shared with its reason, and which ones Retry / Drop fix", () => {
    const held = notShared({
      refused: 1, blocked: 2, conflict: 1,
      items: [
        { kind: "asset", key: "art/big.png", state: "refused", reason: "too big for your plan" },
        { kind: "doc", key: "scene_1", state: "blocked", attempts: 5 },
        { kind: "doc", key: "scene_2", state: "blocked", attempts: 1, deleted: true },
        { kind: "doc", key: "deck", state: "conflict" },
        { kind: "doc", key: "arena", state: "locked_out", reason: "locked by Ana" },
      ],
    });
    expect(held.count).toBe(5);
    expect(held.items.map((item) => item.text)).toEqual([
      "art/big.png: too big for your plan",
      "scene_1: couldn't be sent after 5 tries",
      "scene_2 (deleted here): couldn't be sent after 1 try",
      "deck: changed here and by someone else",
      "arena: locked by Ana",
    ]);
    expect(held.items.map((item) => item.fixable)).toEqual([true, true, true, false, false]);
    // The list holds the newest only; the count is the total.
    expect(notShared({ refused: 60, items: [] }).count).toBe(60);
    expect(notShared({}).count).toBe(0);
  });

  it("the switch says what is sent first and what stays; drop and reset ask first", () => {
    expect(switchConfirm("BrainRot TCG", { kind: "personal", label: "Local" }, { label: "Alpha", pending: 3, held: 1 })).toEqual({
      title: "Switch BrainRot TCG to Local data?",
      message:
        "3 changes not sent to Alpha will be sent first. 1 change not shared stays in Alpha's copy on this PC. " +
        "Nothing is copied. BrainRot TCG restarts with its Local data.",
    });
    expect(switchConfirm("BrainRot TCG", { kind: "shared", label: "Beta" }, { label: "Alpha", pending: 1 }).message).toBe(
      "1 change not sent to Alpha will be sent first. Nothing is copied. BrainRot TCG restarts with Beta's data.",
    );
    expect(switchConfirm("BrainRot TCG", { kind: "shared", label: "Beta" }, { label: "Alpha", pending: 0, held: 0 }).message).toBe(
      "Nothing is copied. BrainRot TCG restarts with Beta's data.",
    );
    expect(dropConfirm("Alpha", "scene_1")).toEqual({
      title: "Drop your change to scene_1?",
      message: "It is removed from this PC and never sent to Alpha.",
    });
    // Upload and Clear are for the space's whole copy here: they name all of it.
    expect(resetConfirm("upload", "Alpha", ["BrainRot TCG", "Forge", "Workflows"])).toEqual({
      title: "Upload your copy of Alpha?",
      message: "This PC's whole copy of Alpha's data is sent again, and everyone in Alpha gets it: BrainRot TCG, Forge and Workflows.",
    });
    expect(resetConfirm("clear", "Alpha", ["Workflows"])).toEqual({
      title: "Clear your copy of Alpha?",
      message: "This PC's whole copy of Alpha's data is deleted: Workflows. Alpha's data on the server comes down instead, and nothing is sent.",
    });
    expect(resetConfirm("clear", "Alpha").message).toBe(
      "This PC's whole copy of Alpha's data is deleted. Alpha's data on the server comes down instead, and nothing is sent.",
    );
    expect([listText([]), listText(["A"]), listText(["A", "B"]), listText(["A", "B", "C"])]).toEqual(
      ["", "A", "A and B", "A, B and C"]);
  });
});

describe("the bar's one status phrase", () => {
  const MB = 1024 ** 2;
  const busy = (): PluginScopeStatus => shared({
    conflicts: [{ kind: "doc", key: "deck", by: "Ana" }],
    locks: [ANA_LOCK, { unit: "doc:x", name: "x", holder: "Ben" }, { unit: "doc:y", mine: true }],
    changes: { held: true, incoming: 2, incomingBy: ["Ana"], sentBytes: 412 * MB, totalBytes: 1200 * MB },
    importing: 40,
    pending: 3,
  });
  const say = (s: PluginScopeStatus) => statusPhrase(s, NOW).text;

  it("a state that stops syncing comes before everything else", () => {
    expect(say({ ...busy(), state: "lost" })).toMatch(/^You no longer have access to Alpha\./);
    expect(say({ ...busy(), state: "locked" })).toBe("Waiting for your account's data key. Read-only until you're back online.");
    expect(say({ ...busy(), state: "error", error: "HTTP 502", nextTry: NOW / 1000 + 40 })).toBe("Not synced: HTTP 502 · retry in 40 s");
    expect(say({ ...busy(), state: "offline" })).toBe("Not synced: offline");
    expect(say({ ...busy(), state: "no_provider" })).toBe("Not connected: Ducky Account isn't running · 3 to send");
    expect(say({ ...busy(), state: "unavailable", error: "permission denied" })).toBe(
      "Alpha isn't available right now (permission denied). Read-only until it's back.");
    expect(say({ ...busy(), state: "reset" })).toBe("Alpha's team data was reset on the server");
    expect(statusPhrase({ ...busy(), state: "error" }, NOW).tone).toBe("error");
  });

  it("then conflicts, a lock, updates waiting, an import, an upload, the queue, up to date", () => {
    const s = busy();
    expect(say(s)).toBe("1 conflict");
    delete s.conflicts;
    expect(say(s)).toBe("Locked by Ana: MEGA_Duel_Stadium and 1 more (read-only for you)");
    s.locks = [{ unit: "doc:y", mine: true }];
    expect(statusPhrase(s, NOW)).toMatchObject({ text: "2 updates from Ana", action: "update" });
    s.changes = { ...s.changes, held: false };
    expect(say(s)).toBe("Moving Alpha's data to the new sync… 40%");
    delete s.importing;
    expect(say(s)).toBe("Sending 412 of 1,200 MB");
    s.changes = { incoming: 2 };
    expect(say(s)).toBe("3 to send · 2 incoming");
    s.pending = 0;
    s.changes = {};
    s.refused = 1;
    expect(statusPhrase(s, NOW)).toMatchObject({ text: "1 can't be sent", tone: "warn" });
    s.refused = 0;
    expect(say(s)).toBe("Up to date · #482 · 2 min ago");
    expect(say({ ...s, state: "waiting" })).toBe("Waiting for Alpha's data…");
    expect(say({ ...s, state: "paused", scope: { ...s.scope!, readOnly: true } })).toBe("Alpha is paused. Read-only.");
    expect(say({ ...s, head: undefined, syncedAt: null })).toBe("Not synced yet");
    expect(say({ ...s, scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false } })).toMatch(/^Only on this PC/);
  });

  it("v1 counts work too: a held change and a conflict count", () => {
    expect(say(shared({ head: undefined, conflict: 2 }))).toBe("2 conflicts");
    expect(say(shared({ head: undefined, pending: 1 }))).toBe("1 to send");
  });

  it("says who else is here, at most two names then +N, never this PC", () => {
    const roster = [
      { user: "u1", user_name: "Ana", device: "ANA-PC", plugins: { forge: { viewing: true, editing: [{ unitName: "MEGA_Duel_Stadium", actor: "user", since: 100 }] } } },
      { user: "u2", user_name: "Ben", device: "BEN-PC", plugins: { forge: { editing: [{ unitName: "Arena", actor: "agent", ducky: "Builder" }] } } },
      { user: "u3", user_name: "Cy", plugins: { forge: { viewing: true } } },
      { user: "u4", user_name: "Di", plugins: { forge: { viewing: true } } },
      { user: "u5", user_name: "Ed", plugins: { other: { viewing: true } } },
      { user: "me", user_name: "Me", me: true, plugins: { forge: { viewing: true } } },
    ];
    const rows = peopleRows(roster, "forge");
    expect(peopleText(rows)).toBe("with Ana (editing MEGA_Duel_Stadium), Ben's ducky Builder +2");
    expect(rows.map(doingText)).toEqual([
      "Editing MEGA_Duel_Stadium", "Ducky Builder editing Arena", "Viewing", "Viewing", "Not in this plugin",
    ]);
    expect(rows[0]).toMatchObject({ name: "Ana", device: "ANA-PC", since: 100 });
    expect(peopleText(peopleRows([{ name: "Ana", doing: "viewing" }, { name: "Ben", doing: "" }], "forge"))).toBe("with Ana");
    expect(peopleText([])).toBe("");
  });

  it("counts locks: others' and mine", () => {
    expect(locksText([ANA_LOCK, { unit: "doc:x", holder: "Ben" }, { unit: "doc:y", mine: true }])).toBe("2 locked · You hold 1");
    expect(locksText([{ unit: "doc:y", mine: true }])).toBe("You hold 1");
    expect(locksText([])).toBe("");
  });

  it("words a refused write, Break, restores, conflicts and outgoing states", () => {
    const at = new Date(2026, 9, 17, 15, 2).getTime() / 1000;
    expect(clockText(at, "en-US")).toBe("3:02 PM");
    expect(refusedWriteText("Forge", { name: "MEGA_Duel_Stadium", holder: "Ana", since: at }, "en-US")).toBe(
      "Forge: MEGA_Duel_Stadium is locked by Ana since 3:02 PM. Your change wasn't saved.");
    expect(refusedWriteText("Forge", { error: "Alpha is paused." })).toBe("Forge: your change wasn't saved. Alpha is paused.");
    expect(breakConfirm("Ana", "MEGA_Duel_Stadium")).toEqual({
      title: "Break Ana's lock on MEGA_Duel_Stadium?",
      message: "Ana is told, and what Ana changed in MEGA_Duel_Stadium and hasn't sent yet becomes a conflict on their PC. " +
        "Nothing of theirs is lost.",
    });
    expect(restoreConfirm("item", "Alpha", { plugin: "Forge", seq: 7, key: "deck" })).toEqual({
      title: "Restore deck to #7?",
      message: "deck goes back to how it was at #7. It is a new change everyone in Alpha gets; the history stays as it is.",
    });
    expect(restoreConfirm("to", "Alpha", { plugin: "Forge", seq: 7 }).title).toBe("Restore Forge to #7?");
    expect(restoreConfirm("undo", "Alpha", { plugin: "Forge", seq: 7 }).title).toBe("Undo change #7?");
    expect(conflictText("deleted", "Ana")).toBe("Ana deleted this; you changed it");
    expect(conflictText(undefined, undefined)).toBe("Changed here and by Someone");
    expect(outgoingStateText("blocked", "file in use", 5)).toBe("Couldn't be sent after 5 tries: file in use");
    expect(outgoingStateText("refused", "too big")).toBe("Refused: too big");
    expect(outgoingStateText("queued")).toBe("Queued");
    expect([durationText(40), durationText(240), durationText(7200)]).toEqual(["40 s", "4 min", "2 h"]);
    expect(sentText(512 * 1024, 900 * 1024)).toBe("512 of 900 KB");
  });
});
