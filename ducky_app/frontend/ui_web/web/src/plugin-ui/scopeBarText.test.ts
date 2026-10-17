import { describe, expect, it } from "vitest";
import {
  dropConfirm,
  listText,
  lostText,
  notShared,
  resetConfirm,
  resetText,
  storageLine,
  switchConfirm,
  syncText,
  unavailableText,
} from "./scopeBarText";

const GB = 1024 ** 3;

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
