import type { FolderDto, FolderItem, SidebarLayoutPatch } from "../types/panel";
import { isArchiveFolderId } from "./archiveFolder";
import { loadFolderOpenState } from "./folderOpenState";

export const PROJECT_FOLDER_PREFIX = "project:";

/** The project slug of the one Duckies list (chats with no island). */
export const GLOBAL_PROJECT_SLUG = "_no_project";

export function isProjectFolderId(id: string): boolean {
  return id.startsWith(PROJECT_FOLDER_PREFIX);
}

export function projectFolderId(slug: string): string {
  return `${PROJECT_FOLDER_PREFIX}${slug}`;
}

export function findFolderById(folders: FolderItem[], id: string): FolderItem | null {
  for (const folder of folders) {
    if (folder.id === id) return folder;
    const nested = findFolderById(folder.children, id);
    if (nested) return nested;
  }
  return null;
}

/** Duckies and nested groups inside a group (its own hub chat not counted). */
export function groupInsideCount(folder: FolderItem): number {
  const own = folder.chats.filter((c) => c.id !== folder.groupHubId).length;
  return folder.children.reduce((sum, child) => sum + 1 + groupInsideCount(child), own);
}

/** Folder ids that must be expanded to reveal a chat in the duckies tree. */
export function findChatAncestorFolderIds(
  folders: FolderItem[],
  rootChats: FolderItem["chats"],
  chatId: string,
): string[] {
  const walk = (items: FolderItem[], ancestors: string[]): string[] | null => {
    for (const folder of items) {
      if (folder.chats.some((chat) => chat.id === chatId)) {
        return [...ancestors, folder.id];
      }
      const nested = walk(folder.children, [...ancestors, folder.id]);
      if (nested) return nested;
    }
    return null;
  };

  if (rootChats.some((chat) => chat.id === chatId)) return [];
  return walk(folders, []) ?? [];
}

export function expandFoldersById(folders: FolderItem[], folderIds: ReadonlySet<string>): FolderItem[] {
  return folders.map((folder) => ({
    ...folder,
    expanded: folderIds.has(folder.id) ? true : folder.expanded,
    children: expandFoldersById(folder.children, folderIds),
  }));
}

export function maxExpandedFolderDepth(folders: FolderItem[], depth = 0): number {
  let max = -1;
  for (const folder of folders) {
    if (folder.expanded) {
      max = Math.max(max, depth);
      max = Math.max(max, maxExpandedFolderDepth(folder.children, depth + 1));
    }
  }
  return max;
}

function collapseChatFoldersOneLevel(folders: FolderItem[], maxDepth: number, depth = 0): FolderItem[] {
  return folders.map((folder) => ({
    ...folder,
    expanded: depth === maxDepth ? false : folder.expanded,
    children: collapseChatFoldersOneLevel(folder.children, maxDepth, depth + 1),
  }));
}

function expandChatFoldersOneLevel(
  folders: FolderItem[],
  targetDepth: number,
  depth = 0,
  parentExpanded = true,
): FolderItem[] {
  return folders.map((folder) => {
    const expanded = depth === targetDepth && parentExpanded ? true : folder.expanded;
    return {
      ...folder,
      expanded,
      children: expandChatFoldersOneLevel(folder.children, targetDepth, depth + 1, expanded),
    };
  });
}

export function toggleChatFolderLevels(folders: FolderItem[]): FolderItem[] {
  const maxDepth = maxExpandedFolderDepth(folders);
  if (maxDepth >= 0) return collapseChatFoldersOneLevel(folders, maxDepth);
  return expandChatFoldersOneLevel(folders, 0);
}

export function chatFolderSiblingNames(folders: FolderItem[], parentId: string): string[] {
  if (!parentId) return folders.map((f) => f.name);
  const parent = findFolderById(folders, parentId);
  return parent ? parent.children.map((c) => c.name) : folders.map((f) => f.name);
}

/**
 * Place a just-created folder into the tree without waiting for a reload, so the
 * row is on screen (and namable by the next create) the moment the API returns.
 */
export function insertChatFolder(
  folders: FolderItem[],
  parentId: string,
  folder: Omit<FolderItem, "parentId" | "sortOrder">,
): FolderItem[] {
  const asChildOf = (parent: string, siblings: FolderItem[]): FolderItem => ({
    ...folder,
    parentId: parent,
    sortOrder: siblings.reduce((max, f) => Math.max(max, f.sortOrder), 0) + 1,
  });

  if (parentId && findFolderById(folders, parentId)) {
    const walk = (items: FolderItem[]): FolderItem[] =>
      items.map((item) =>
        item.id === parentId
          ? { ...item, expanded: true, children: [...item.children, asChildOf(parentId, item.children)] }
          : { ...item, children: walk(item.children) },
      );
    return walk(folders);
  }
  return [...folders, asChildOf("", folders)];
}

export function chatNamesInFolder(
  folders: FolderItem[],
  folderId: string,
  rootChats: FolderItem["chats"] = [],
): string[] {
  if (!folderId) return rootChats.map((c) => c.name);
  const folder = findFolderById(folders, folderId);
  return folder ? folder.chats.map((c) => c.name) : [];
}

export type SidebarDragKind = "folder" | "chat";

export function dragId(kind: SidebarDragKind, id: string): string {
  return `${kind}:${id}`;
}

export function parseDragId(raw: string): { kind: SidebarDragKind; id: string } | null {
  const idx = raw.indexOf(":");
  if (idx <= 0) return null;
  const kind = raw.slice(0, idx) as SidebarDragKind;
  if (kind !== "folder" && kind !== "chat") return null;
  return { kind, id: raw.slice(idx + 1) };
}

export function buildFolderTree(
  folderRows: FolderDto[],
  chatsByFolder: Map<string, FolderItem["chats"]>,
  expandedById: Map<string, boolean>,
): FolderItem[] {
  const nodes = new Map<string, FolderItem>();
  for (const row of folderRows) {
    if (isArchiveFolderId(row.id)) continue;
    const hubId = (row.group_hub_id || "").trim();
    const rawChats = chatsByFolder.get(row.id) ?? [];
    // Hub chat is the folder itself — don't list it as a child ducky.
    const chats = hubId ? rawChats.filter((c) => c.id !== hubId && !c.isGroup) : rawChats;
    nodes.set(row.id, {
      id: row.id,
      name: row.name,
      parentId: row.parent_id || "",
      sortOrder: Number(row.sort_order) || 0,
      expanded: true, // set below once the depth is known
      chats,
      children: [],
      groupHubId: hubId || undefined,
    });
  }

  const roots: FolderItem[] = [];
  for (const node of nodes.values()) {
    if (node.parentId && nodes.has(node.parentId)) {
      nodes.get(node.parentId)!.children.push(node);
    } else {
      node.parentId = "";
      roots.push(node);
    }
  }

  // On screen state first, then the saved state; a folder never seen opens at the top
  // level only, so a new swarm's sub-groups start closed.
  const saved = loadFolderOpenState();
  const setExpanded = (list: FolderItem[], depth: number) => {
    for (const item of list) {
      item.expanded = expandedById.get(item.id) ?? saved[item.id] ?? depth === 0;
      setExpanded(item.children, depth + 1);
    }
  };
  setExpanded(roots, 0);

  const sortFolderList = (list: FolderItem[]) => {
    list.sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name));
    for (const item of list) {
      // A group's lead sits at the top of its group.
      const leads = (c: FolderItem["chats"][number]) =>
        item.groupHubId && c.isLeader && c.parentConvId === item.groupHubId ? 1 : 0;
      item.chats.sort((a, b) => leads(b) - leads(a)
        || (a.sortOrder ?? 0) - (b.sortOrder ?? 0) || a.name.localeCompare(b.name));
      sortFolderList(item.children);
    }
  };
  sortFolderList(roots);
  return roots;
}

/** One project's order and nesting, as saved by apply_sidebar_layout. */
export function flattenLayout(roots: FolderItem[], rootChats: FolderItem["chats"] = []): SidebarLayoutPatch {
  const folders: SidebarLayoutPatch["folders"] = [];
  const chats: SidebarLayoutPatch["chats"] = [];

  rootChats.forEach((chat, chatIndex) => {
    chat.sortOrder = chatIndex;
    chats.push({ id: chat.id, folder_id: "", sort_order: chatIndex });
  });

  const walkSiblings = (siblings: FolderItem[], parentId: string) => {
    siblings.forEach((folder, index) => {
      folder.parentId = parentId;
      folder.sortOrder = index;
      folders.push({ id: folder.id, parent_id: parentId, sort_order: index });
      folder.chats.forEach((chat, chatIndex) => {
        chat.sortOrder = chatIndex;
        chats.push({ id: chat.id, folder_id: folder.id, sort_order: chatIndex });
      });
      walkSiblings(folder.children, folder.id);
    });
  };

  walkSiblings(roots, "");
  return { folders, chats };
}

export function flattenFoldersForSelect(roots: FolderItem[], depth = 0): { id: string; label: string }[] {
  const out: { id: string; label: string }[] = [];
  for (const folder of roots) {
    if (isArchiveFolderId(folder.id)) continue;
    const prefix = depth > 0 ? `${"— ".repeat(depth)}` : "";
    out.push({ id: folder.id, label: `${prefix}${folder.name}` });
    out.push(...flattenFoldersForSelect(folder.children, depth + 1));
  }
  return out;
}
