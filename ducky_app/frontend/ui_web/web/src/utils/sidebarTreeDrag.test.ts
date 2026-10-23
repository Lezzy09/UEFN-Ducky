import { describe, expect, it } from "vitest";
import type { FolderItem } from "../types/panel";
import { flattenLayout, insertChatFolder } from "./sidebarTree";
import { buildDuckiesIndex, duckiesLayoutFor, duckiesPlace } from "./duckiesTreeModel";

function folder(id: string, name: string, children: FolderItem[] = []): FolderItem {
  return {
    id,
    name,
    parentId: "",
    expanded: true,
    sortOrder: 0,
    chats: [],
    children,
  };
}

describe("one Duckies list", () => {
  it("saves the list's own layout: folders, nesting and root chats", () => {
    const data = { folders: [folder("f0", "Code", [folder("f1", "Art")])], rootChats: [{ id: "c1", name: "A" }] };
    const patch = duckiesLayoutFor(data, "_no_project", "_no_project")!;
    expect(patch.project_slug).toBe("_no_project");
    expect(patch.folders).toEqual([
      { id: "f0", parent_id: "", sort_order: 0 },
      { id: "f1", parent_id: "f0", sort_order: 0 },
    ]);
    expect(patch.chats.map((c) => c.id)).toEqual(["c1"]);
  });

  it("flattenLayout numbers root chats and folder chats in order", () => {
    const code: FolderItem = { ...folder("f0", "Code"), chats: [{ id: "c2", name: "B" }, { id: "c3", name: "C" }] };
    const patch = flattenLayout([code], [{ id: "c1", name: "A" }]);
    expect(patch.chats).toEqual([
      { id: "c1", folder_id: "", sort_order: 0 },
      { id: "c2", folder_id: "f0", sort_order: 0 },
      { id: "c3", folder_id: "f0", sort_order: 1 },
    ]);
  });

  it("a drop on blank space or a folder targets the list's project and that folder", () => {
    const index = buildDuckiesIndex({ folders: [folder("f1", "Art")], rootChats: [] }, "_no_project");
    expect(duckiesPlace(index, index.currentRootId)).toEqual({ slug: "_no_project", folderId: "" });
    expect(duckiesPlace(index, "folder:f1")).toEqual({ slug: "_no_project", folderId: "f1" });
  });

  it("a new top-level folder lands last at the top level", () => {
    const next = insertChatFolder([folder("f0", "Code")], "", { id: "f9", name: "New", expanded: true, chats: [], children: [] });
    expect(next.map((f) => f.id)).toEqual(["f0", "f9"]);
    expect(next[1].parentId).toBe("");
  });
});
