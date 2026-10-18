import { describe, expect, it } from "vitest";
import { agoText, withLive } from "./OtherDuckiesChats";

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
