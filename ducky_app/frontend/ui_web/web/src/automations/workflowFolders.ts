import type { AutomationSummaryDto } from "../types/panel";

export type FolderNode = {
  path: string;
  name: string;
  folders: FolderNode[];
  rows: AutomationSummaryDto[];
  /** Workflows in this folder and every folder inside it. */
  count: number;
};

/** Same tidy-up as the host: trimmed names, no empty parts, "/" between. */
export function normalizeFolder(raw: string | undefined | null): string {
  return String(raw || "").replace(/\\/g, "/").split("/").map((part) => part.split(/\s+/).filter(Boolean).join(" ").slice(0, 64)).filter(Boolean).join("/");
}

export function folderName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

export function parentFolder(path: string): string {
  const at = path.lastIndexOf("/");
  return at < 0 ? "" : path.slice(0, at);
}

export function joinFolder(parent: string, name: string): string {
  return normalizeFolder(parent ? `${parent}/${name}` : name);
}

export function isInside(path: string, folder: string): boolean {
  return path === folder || path.startsWith(`${folder}/`);
}

/** Where ``path`` ends up when folder ``from`` moves to ``to`` (null = not affected). */
export function movedPath(path: string, from: string, to: string): string | null {
  if (!isInside(path, from)) return null;
  return normalizeFolder(to + path.slice(from.length));
}

/** One owner's rows as a folder tree. ``extra`` keeps folders that hold nothing yet. */
export function buildFolderTree(rows: AutomationSummaryDto[], extra: string[] = []): FolderNode {
  const root: FolderNode = { path: "", name: "", folders: [], rows: [], count: 0 };
  const byPath = new Map<string, FolderNode>([["", root]]);
  const ensure = (path: string): FolderNode => {
    const found = byPath.get(path);
    if (found) return found;
    const parent = ensure(parentFolder(path));
    const node: FolderNode = { path, name: folderName(path), folders: [], rows: [], count: 0 };
    parent.folders.push(node);
    byPath.set(path, node);
    return node;
  };
  for (const path of extra) ensure(normalizeFolder(path));
  for (const row of rows) ensure(normalizeFolder(row.folder)).rows.push(row);
  const finish = (node: FolderNode): number => {
    node.folders.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }));
    node.count = node.rows.length + node.folders.reduce((sum, child) => sum + finish(child), 0);
    return node.count;
  };
  finish(root);
  return root;
}

/** Every folder path in a tree (for "Move to folder"). */
export function folderPaths(node: FolderNode): string[] {
  return node.folders.flatMap((child) => [child.path, ...folderPaths(child)]);
}

const EMPTY_FOLDERS_KEY = "ducky.workflows.emptyFolders.v1";

/** Folders made on this PC that hold no workflow yet (a folder with workflows comes from them). */
export function loadEmptyFolders(): Record<string, string[]> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(EMPTY_FOLDERS_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).map(([owner, paths]) => [owner, Array.isArray(paths) ? paths.map((path) => normalizeFolder(String(path))).filter(Boolean) : []]));
  } catch {
    return {};
  }
}

export function saveEmptyFolders(folders: Record<string, string[]>): void {
  try {
    window.localStorage.setItem(EMPTY_FOLDERS_KEY, JSON.stringify(folders));
  } catch {
    /* private mode or blocked storage: empty folders last until reload */
  }
}
