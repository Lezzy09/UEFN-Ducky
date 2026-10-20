import { describe, expect, it } from "vitest";
import { badgeText, onlineCount, othersLine, sortDuckies } from "./DuckiesDropdown";
import { remoteDuckyLine } from "./RemoteDuckyBar";

describe("sortDuckies", () => {
  it("puts this Ducky first, then the reachable ones, each by name, and drops rows without a key", () => {
    const rows = sortDuckies([
      { keyId: "c", name: "Zed", live: false },
      { keyId: "b", name: "Laptop", live: true },
      { keyId: "a", name: "Desk", mine: true },
      { name: "no key" },
      { keyId: "d", live: true },
    ]);
    expect(rows.map((r) => r.keyId)).toEqual(["a", "b", "d", "c"]);
    expect(rows[2].name).toBe("UEFN Ducky");
  });
});

describe("othersLine", () => {
  it("counts the other Duckies you can reach now", () => {
    const me = { keyId: "a", name: "Desk", live: true, mine: true };
    expect(othersLine([me])).toBe("");
    expect(othersLine([me, { keyId: "b", name: "Laptop", live: true, mine: false }, { keyId: "c", name: "Old", live: false, mine: false }])).toBe("1 of 2 online");
    expect(othersLine([me, { keyId: "c", name: "Old", live: false, mine: false }])).toBe("None online");
  });
});

describe("remoteDuckyLine", () => {
  it("names the Ducky you're talking to and the link state", () => {
    expect(remoteDuckyLine("Laptop", null)).toEqual({ text: "Connecting to Laptop…", tone: "wait" });
    expect(remoteDuckyLine("Laptop", { state: "live", reason: "", desktopVersion: "1.2.3" })).toEqual({ text: "Talking to Laptop", tone: "live" });
    expect(remoteDuckyLine("Laptop", { state: "failed", reason: "It didn't answer.", desktopVersion: "" })).toEqual({
      text: "Can't reach Laptop. It didn't answer.",
      tone: "off",
    });
  });
});

describe("onlineCount and badgeText", () => {
  it("counts your other online Duckies plus online people from plugins, capped at 9+", () => {
    const me = { keyId: "a", name: "Desk", live: true, mine: true };
    const laptop = { keyId: "b", name: "Laptop", live: true, mine: false };
    const old = { keyId: "c", name: "Old", live: false, mine: false };
    const team = { id: "team", label: "Team", people: [
      { id: "1", name: "Ana", detail: "", online: true },
      { id: "2", name: "Ben", detail: "", online: false },
    ] };
    expect(onlineCount([me, laptop, old], [team])).toBe(2);
    expect(onlineCount([me])).toBe(0);
    expect([0, 1, 9, 10, 42].map(badgeText)).toEqual(["", "1", "9", "9+", "9+"]);
  });
});
