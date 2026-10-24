/** Persist each sidebar folder's open/closed state across reloads. */

import type { FolderItem } from "../types/panel";

const KEY = "uefn-folder-open";

let lastWritten = "";

export function loadFolderOpenState(): Record<string, boolean> {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/** Save every folder's expanded flag; folders saved before but not in this tree keep theirs. */
export function saveFolderOpenState(folders: FolderItem[]): void {
  if (!folders.length) return;
  const state = loadFolderOpenState();
  const walk = (items: FolderItem[]) => {
    for (const item of items) {
      state[item.id] = item.expanded;
      walk(item.children);
    }
  };
  walk(folders);
  const raw = JSON.stringify(state);
  if (raw === lastWritten) return;
  lastWritten = raw;
  try {
    localStorage.setItem(KEY, raw);
  } catch {
    /* ignore */
  }
}
