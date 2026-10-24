// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import type { FolderDto, FolderItem } from "../types/panel";
import { buildFolderTree } from "./sidebarTree";
import { saveFolderOpenState } from "./folderOpenState";

function row(id: string, parentId = ""): FolderDto {
  return { id, name: id, parent_id: parentId, sort_order: 0 } as FolderDto;
}

function flat(items: FolderItem[]): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  const walk = (list: FolderItem[]) => list.forEach((f) => { out[f.id] = f.expanded; walk(f.children); });
  walk(items);
  return out;
}

const build = (rows: FolderDto[], inMemory = new Map<string, boolean>()) =>
  buildFolderTree(rows, new Map(), inMemory);

describe("folder open state", () => {
  beforeEach(() => localStorage.clear());

  it("collapsed folders stay collapsed after a remount", () => {
    const rows = [row("a"), row("b"), row("c"), row("a1", "a")];
    const tree = build(rows, new Map([["a", false], ["b", false], ["c", false], ["a1", true]]));
    saveFolderOpenState(tree);
    // Remount: no folders in memory, only what was saved.
    expect(flat(build(rows))).toEqual({ a: false, b: false, c: false, a1: true });
  });

  it("a new 14-seat swarm shows its sub-groups closed", () => {
    const rows = [row("swarm")];
    for (let g = 0; g < 4; g++) {
      rows.push(row(`g${g}`, "swarm"));
      rows.push(row(`g${g}-inner`, `g${g}`));
    }
    const state = flat(build(rows));
    expect(state.swarm).toBe(true);
    for (const [id, open] of Object.entries(state)) if (id !== "swarm") expect(open).toBe(false);
  });

  it("what is on screen wins over what was saved", () => {
    saveFolderOpenState(build([row("a")], new Map([["a", false]])));
    expect(flat(build([row("a")], new Map([["a", true]])))).toEqual({ a: true });
  });
});
