import { describe, expect, it } from "vitest";
import type { FolderItem } from "../types/panel";
import { resolveDropTarget, TREE_ROOT } from "../tree-dnd/treeMove";
import {
  buildDuckiesIndex,
  duckiesCreateTarget,
  duckiesDropPolicy,
  duckiesLayoutFor,
  duckiesPlaces,
  planDuckiesDrop,
  planDuckiesRestore,
  removeFromDuckies,
  type DuckiesTreeData,
} from "./duckiesTreeModel";

type Chat = FolderItem["chats"][number];
const chat = (id: string, extra: Partial<Chat> = {}): Chat => ({ id, name: id, ...extra });
function folder(id: string, chats: Chat[] = [], children: FolderItem[] = [], extra: Partial<FolderItem> = {}): FolderItem {
  return { id, name: id, parentId: "", sortOrder: 0, expanded: true, chats, children, ...extra };
}

/** The one Duckies list ("here"): a group with a sub-folder, a folder still tagged with
 *  another project, and two single chats. */
function oneList(): DuckiesTreeData {
  return {
    folders: [
      folder("squad", [chat("m1"), chat("m2")], [folder("inner", [chat("i1")])], { groupHubId: "hub" }),
      folder("art", [chat("a1", { projectSlug: "other" })], [], { projectSlug: "other" }),
    ],
    rootChats: [chat("c1"), chat("c2")],
  };
}

const ids = (chats: Chat[]) => chats.map((c) => c.id);

describe("Duckies moves", () => {
  it("reorders between rows and saves the list's layout", () => {
    const data = oneList();
    const index = buildDuckiesIndex(data, "here");
    const policy = duckiesDropPolicy(index);
    const target = resolveDropTarget(index.model, ["chat:c2"], "chat:c1", "before", policy)!;
    const plan = planDuckiesDrop(index, data, ["chat:c2"], target, policy);
    expect(ids(plan.data.rootChats)).toEqual(["c2", "c1"]);
    expect(plan.projectMoves).toEqual([]);
    expect(plan.layoutSlugs).toEqual(["here"]);
    const patch = duckiesLayoutFor(plan.data, "here", "here")!;
    expect(patch.chats.filter((c) => !c.folder_id).map((c) => c.id)).toEqual(["c2", "c1"]);
    expect(patch.folders.map((f) => f.id)).toEqual(["squad", "inner", "art"]);
    expect(duckiesLayoutFor(plan.data, "other", "here")).toBeNull();
  });

  it("drops into a group, and a group moves with its members and sub-folders", () => {
    const data = oneList();
    const index = buildDuckiesIndex(data, "here");
    const policy = duckiesDropPolicy(index);
    const into = resolveDropTarget(index.model, ["chat:c1"], "folder:squad", "into", policy)!;
    const joined = planDuckiesDrop(index, data, ["chat:c1"], into, policy).data;
    expect(ids(joined.folders[0].chats)).toEqual(["m1", "m2", "c1"]);

    // The squad group goes into a folder of another project: members and nested folder too.
    const nest = resolveDropTarget(index.model, ["folder:squad"], "folder:art", "into", policy)!;
    const plan = planDuckiesDrop(index, data, ["folder:squad"], nest, policy);
    const art = plan.data.folders.find((f) => f.id === "art")!;
    const squad = art.children.find((f) => f.id === "squad")!;
    expect(ids(squad.chats)).toEqual(["m1", "m2"]);
    expect(squad.children.map((f) => f.id)).toEqual(["inner"]);
    expect(squad.projectSlug).toBe("other");
    // Changing project goes through the host's project move, into that folder.
    expect(plan.projectMoves).toEqual([{ slug: "other", folderId: "art", convIds: [], folderIds: ["squad"] }]);
    expect(plan.layoutSlugs).toEqual(["other"]);
  });

  it("never nests a group into itself or into its own sub-folder", () => {
    const data = oneList();
    const index = buildDuckiesIndex(data, "here");
    const policy = duckiesDropPolicy(index);
    expect(resolveDropTarget(index.model, ["folder:squad"], "folder:squad", "into", policy)).toBeNull();
    expect(resolveDropTarget(index.model, ["folder:squad"], "folder:inner", "into", policy)).toBeNull();
    expect(resolveDropTarget(index.model, ["folder:squad"], "chat:i1", "before", policy)).toBeNull();
  });

  it("blank space drops onto the list's root; the top level itself takes nothing", () => {
    const data = oneList();
    const index = buildDuckiesIndex(data, "here");
    const policy = duckiesDropPolicy(index);
    const target = resolveDropTarget(index.model, ["chat:a1"], null, "into", policy)!;
    expect(target.parentId).toBe(index.currentRootId);
    expect(planDuckiesDrop(index, data, ["chat:a1"], target, policy).projectMoves).toEqual([
      { slug: "here", folderId: "", convIds: ["a1"], folderIds: [] },
    ]);
    expect(policy.acceptsDrop?.(TREE_ROOT, ["chat:c1"])).toBe(false);
  });

  it("undo puts a moved group back in its project and place", () => {
    const data = oneList();
    const index = buildDuckiesIndex(data, "here");
    const policy = duckiesDropPolicy(index);
    const places = duckiesPlaces(index, ["folder:squad", "chat:c2"]);
    const target = resolveDropTarget(index.model, ["folder:squad", "chat:c2"], "folder:art", "into", policy)!;
    const after = planDuckiesDrop(index, data, ["folder:squad", "chat:c2"], target, policy).data;
    const back = planDuckiesRestore(buildDuckiesIndex(after, "here"), after, places);
    expect(ids(back.data.rootChats)).toEqual(["c1", "c2"]);
    expect(back.data.folders.map((f) => f.id)[0]).toBe("squad");
    expect(back.projectMoves).toEqual([{ slug: "here", folderId: "", convIds: ["c2"], folderIds: ["squad"] }]);
    expect(back.layoutSlugs.sort()).toEqual(["here"]);
  });
});

describe("deleted rows leave the tree at once", () => {
  it("drops deleted chats and folders; a removed group's duckies stay unless archived with it", () => {
    const data = oneList();
    const kept = removeFromDuckies(data, { chatIds: ["c1", "a1"], folderIds: ["squad"] });
    expect(ids(kept.rootChats)).toEqual(["c2", "m1", "m2"]);
    expect(kept.folders.map((f) => f.id)).toEqual(["art", "inner"]);
    expect(ids(kept.folders[0].chats)).toEqual([]);
    const gone = removeFromDuckies(data, { folderIds: ["squad"], keepContents: false });
    expect(ids(gone.rootChats)).toEqual(["c1", "c2"]);
    expect(gone.folders.map((f) => f.id)).toEqual(["art"]);
    expect(removeFromDuckies(data, {})).toBe(data);
  });
});

describe("creating inside a folder", () => {
  it("creates in the folder, with its project when that is not the list's own", () => {
    const data = oneList();
    expect(duckiesCreateTarget("art", "here", data.folders)).toEqual({ folderId: "art", projectSlug: "other" });
    expect(duckiesCreateTarget("squad", "here", data.folders)).toEqual({ folderId: "squad" });
    expect(duckiesCreateTarget("missing", "here", data.folders)).toEqual({ folderId: "" });
    expect(duckiesCreateTarget("", "here", data.folders)).toEqual({ folderId: "" });
  });
});
