import type { FolderItem } from "../types/panel";

export interface GlobalAgentChat {
  id: string;
  name: string;
  duckyName?: string;
  profileId?: string;
  projectSlug?: string;
  updated?: number;
  isGroup?: boolean;
}

/** Chats currently in the Duckies tree (archive is not included). */
export function chatsInDuckiesTree(
  folders: FolderItem[],
  rootChats: FolderItem["chats"],
): GlobalAgentChat[] {
  const out: GlobalAgentChat[] = [...rootChats];
  const walk = (items: FolderItem[]) => {
    for (const folder of items) {
      out.push(...folder.chats);
      walk(folder.children);
    }
  };
  walk(folders);
  return out;
}

function onThisProject(chat: GlobalAgentChat, projectSlug: string): boolean {
  const slug = (chat.projectSlug || "").trim();
  if (!slug || slug === "_no_project") return true;
  return Boolean(projectSlug) && slug === projectSlug;
}

function namedForProfile(chat: GlobalAgentChat, profileName: string): boolean {
  const want = profileName.trim().toLowerCase();
  if (!want) return false;
  const title = chat.name.trim().toLowerCase();
  const ducky = (chat.duckyName || "").trim().toLowerCase();
  return title === want || ducky === want;
}

export interface ProfileAgentChat {
  id: string;
  title?: string;
  ducky_name?: string;
  profile_id?: string;
  folder_id?: string;
  is_group?: boolean;
  is_subagent?: boolean;
  updated?: number;
  project_slug?: string;
}

/** The live chat for a library agent. This island wins; a renamed chat does not count. */
export function pickAgentChatForProfile(
  convs: readonly ProfileAgentChat[],
  profileId: string,
  name: string,
  openSlug = "",
): { id: string; name: string } | null {
  const pid = profileId.trim();
  const want = name.trim().toLowerCase();
  if (!pid) return null;
  const pool = convs.filter((row) => {
    if ((row.profile_id || "").trim() !== pid) return false;
    if (row.is_group || row.is_subagent) return false;
    if ((row.folder_id || "").trim() === "archive") return false;
    const title = (row.title || "").trim().toLowerCase();
    const ducky = (row.ducky_name || "").trim().toLowerCase();
    return Boolean(want) && (title === want || ducky === want);
  });
  if (!pool.length) return null;
  const slug = openSlug.trim();
  const here = slug
    ? pool.filter((row) => {
        const s = (row.project_slug || "").trim();
        return !s || s === "_no_project" || s === slug;
      })
    : [];
  const list = here.length ? here : pool;
  const best = list.reduce((a, b) => ((b.updated || 0) >= (a.updated || 0) ? b : a));
  return { id: best.id, name: (best.title || name).trim() || name };
}

/**
 * The chat this island already has for a library agent, or null so the caller
 * can create one. A renamed chat (General Helper on the Level Designer profile)
 * does not count — the row should open a chat that still wears that name.
 */
export function pickChatForGlobalAgent(
  chats: readonly GlobalAgentChat[],
  profile: { id: string; name: string },
  projectSlug: string,
): { id: string; name: string } | null {
  const pid = profile.id.trim();
  if (!pid) return null;
  let best: GlobalAgentChat | null = null;
  for (const chat of chats) {
    if (chat.isGroup) continue;
    if ((chat.profileId || "").trim() !== pid) continue;
    if (!onThisProject(chat, projectSlug)) continue;
    if (!namedForProfile(chat, profile.name)) continue;
    if (!best || (chat.updated || 0) >= (best.updated || 0)) best = chat;
  }
  return best ? { id: best.id, name: best.name } : null;
}
