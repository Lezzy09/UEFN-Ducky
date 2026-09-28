import { beforeEach, describe, expect, it } from "vitest";
import { pluginPrefsKey, setPluginPrefsAccount } from "./pluginPrefsStorage";

const mem = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (k: string) => (mem.has(k) ? mem.get(k)! : null),
    setItem: (k: string, v: string) => void mem.set(k, String(v)),
    removeItem: (k: string) => void mem.delete(k),
    key: (i: number) => [...mem.keys()][i] ?? null,
    get length() {
      return mem.size;
    },
  },
});

const read = () => JSON.parse(localStorage.getItem(pluginPrefsKey()) || "{}");

describe("plugin prefs per account", () => {
  beforeEach(() => mem.clear());

  it("hands the old shared bag to the first account, and never shows it to the next", () => {
    mem.set("uefn-plugin-ui-prefs", JSON.stringify({ discord: { showInHeader: true } }));
    expect(read()).toEqual({ discord: { showInHeader: true } }); // before the first account check

    expect(setPluginPrefsAccount("https://uefnducky.org|ana@x.org")).toBe(true);
    expect(read()).toEqual({ discord: { showInHeader: true } });
    expect(mem.has("uefn-plugin-ui-prefs")).toBe(false);
    expect(setPluginPrefsAccount("https://uefnducky.org|ana@x.org")).toBe(false);

    // Switch to Bo: Ana's bag is dropped, Bo starts empty (his disk prefs load next).
    expect(setPluginPrefsAccount("https://uefnducky.org|bo@x.org")).toBe(true);
    expect(read()).toEqual({});
    expect([...mem.keys()].some((k) => k.includes("ana@x.org"))).toBe(false);
    localStorage.setItem(pluginPrefsKey(), JSON.stringify({ translation: { language: "es" } }));

    // Signed out: its own empty bag; Bo's is gone.
    setPluginPrefsAccount("");
    expect(read()).toEqual({});
    expect([...mem.keys()].some((k) => k.includes("bo@x.org"))).toBe(false);
  });
});
