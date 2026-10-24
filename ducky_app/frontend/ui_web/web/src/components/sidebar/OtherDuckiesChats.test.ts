import { describe, expect, it } from "vitest";
import { agoText, resizedHeight, withLive } from "./OtherDuckiesChats";
import { groupInsideCount } from "../../utils/sidebarTree";
import type { FolderItem } from "../../types/panel";

describe("resizedHeight", () => {
  it("grows when the handle goes up and stays between the minimum and the room left", () => {
    expect(resizedHeight(160, -40, 600)).toBe(200);
    expect(resizedHeight(160, 500, 600)).toBe(60);
    expect(resizedHeight(160, -900, 300)).toBe(300);
  });
});

describe("groupInsideCount", () => {
  it("counts duckies and nested groups, not the group's own hub", () => {
    const folder = (id: string, chats: string[], children: FolderItem[] = [], hub = ""): FolderItem =>
      ({ id, name: id, parentId: "", sortOrder: 0, expanded: true, groupHubId: hub, children,
         chats: chats.map((c) => ({ id: c, name: c })) }) as unknown as FolderItem;
    const nested = folder("g2", ["h2", "m3"], [], "h2");
    expect(groupInsideCount(folder("g1", ["h1", "m1", "m2"], [nested], "h1"))).toBe(4);
    expect(groupInsideCount(folder("g3", ["h3"], [], "h3"))).toBe(0);
  });
});

describe("agoText", () => {
  it("says how long ago a copy was made", () => {
    const now = 1_000_000;
    expect(agoText(0, now)).toBe("never");
    expect(agoText(now - 5, now)).toBe("just now");
    expect(agoText(now - 300, now)).toBe("5 min ago");
    expect(agoText(now - 3 * 3600, now)).toBe("3 h ago");
    expect(agoText(now - 2 * 86400, now)).toBe("2 d ago");
  });
});

describe("withLive", () => {
  it("shows only Duckies with chats, the reachable ones first", () => {
    const chat = { conv_id: "c1", title: "Lobby", updated: 1, synced: 1 };
    const peers = [
      { ducky: "k3", name: "Zed", synced: 1, chats: [chat] },
      { ducky: "k2", name: "Laptop", synced: 1, chats: [chat] },
      { ducky: "k4", name: "Empty", synced: 1, chats: [] },
    ];
    const shown = withLive(peers, { k3: true });
    expect(shown.map((p) => [p.ducky, p.live])).toEqual([
      ["k3", true],
      ["k2", false],
    ]);
  });
});
