import { describe, expect, it } from "vitest";
import { laneOverlaps, overlapNotes, pathsOverlap } from "./lanes";

describe("lanes", () => {
  it("reports two seats with the same path", () => {
    const overlaps = laneOverlaps([
      { name: "Store lead", paths: ["store/**", "ui/index.html"] },
      { name: "Plugin core", paths: ["ui/index.html"] },
      { name: "Tester", paths: [] },
    ]);
    expect(overlaps).toEqual([{ seat: "Store lead", other: "Plugin core", path: "ui/index.html" }]);
    expect(overlapNotes("Store lead", overlaps)).toEqual(["Store lead ⚠ lane overlaps Plugin core: ui/index.html"]);
    expect(overlapNotes("Plugin core", overlaps)).toEqual(["Plugin core ⚠ lane overlaps Store lead: ui/index.html"]);
  });

  it("globs clash with what they cover, not with siblings", () => {
    expect(pathsOverlap("ui/**", "ui/index.html")).toBe("ui/index.html");
    expect(pathsOverlap("Content\\Verse\\**", "Content/Verse/Shop/**")).toBe("Content/Verse/Shop/**");
    expect(pathsOverlap("Content/Verse/Shop/**", "Content/Verse/Bank/**")).toBeNull();
    expect(pathsOverlap("a.ts", "b.ts")).toBeNull();
    expect(laneOverlaps([{ name: "A", paths: ["a/**"] }, { name: "B", paths: ["b/**"] }])).toEqual([]);
  });
});
