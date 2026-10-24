// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FolderItem } from "../types/panel";
import { findFolderById } from "../utils/sidebarTree";
import { useRevealFocusedChats } from "./ChatSidebar";

function folder(id: string, parentId: string, expanded: boolean, chatIds: string[], children: FolderItem[] = []): FolderItem {
  return {
    id,
    name: id,
    parentId,
    sortOrder: 0,
    expanded,
    chats: chatIds.map((cid) => ({ id: cid, name: cid })) as FolderItem["chats"],
    children,
  };
}

/** QA > Matrix > lead; Other > other-chat. */
function tree(qaOpen: boolean, matrixOpen: boolean): FolderItem[] {
  return [
    folder("qa", "", qaOpen, [], [folder("matrix", "qa", matrixOpen, ["lead"])]),
    folder("other", "", false, ["other-chat"]),
  ];
}

describe("useRevealFocusedChats", () => {
  it("reveals once per focus change; reloads keep a collapsed ancestor shut", () => {
    let state = tree(false, false);
    const setFolders = vi.fn((update: React.SetStateAction<FolderItem[]>) => {
      state = typeof update === "function" ? update(state) : update;
    });
    const { rerender } = renderHook(
      ({ active, folders }) => useRevealFocusedChats(active, folders, [], setFolders),
      { initialProps: { active: ["lead"], folders: state } },
    );
    expect(findFolderById(state, "qa")?.expanded).toBe(true);
    expect(findFolderById(state, "matrix")?.expanded).toBe(true);

    setFolders.mockClear();
    for (let i = 0; i < 5; i += 1) rerender({ active: ["lead"], folders: tree(true, false) });
    expect(setFolders).not.toHaveBeenCalled();

    state = tree(true, false);
    rerender({ active: ["other-chat"], folders: state });
    expect(findFolderById(state, "other")?.expanded).toBe(true);
    expect(findFolderById(state, "matrix")?.expanded).toBe(false);
  });

  it("reveals a focused chat on the first load that contains it", () => {
    let state: FolderItem[] = [];
    const setFolders = vi.fn((update: React.SetStateAction<FolderItem[]>) => {
      state = typeof update === "function" ? update(state) : update;
    });
    const { rerender } = renderHook(
      ({ folders }) => useRevealFocusedChats(["lead"], folders, [], setFolders),
      { initialProps: { folders: state } },
    );
    expect(setFolders).not.toHaveBeenCalled();
    state = tree(false, false);
    rerender({ folders: state });
    expect(findFolderById(state, "matrix")?.expanded).toBe(true);
  });
});
