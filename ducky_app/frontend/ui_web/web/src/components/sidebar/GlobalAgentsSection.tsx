import { useState } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { DuckyAvatar, DUCKY_AVATAR_SIZES } from "../ducky/DuckyAvatars";
import { formToConfig, profileToForm } from "../ducky/duckyProfileForm";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import type { AgentProfileDto, FolderItem } from "../../types/panel";
import { chatsInDuckiesTree, pickChatForGlobalAgent } from "../../utils/globalAgents";
import { dragId, globalProjectChats, GLOBAL_PROJECT_SLUG, nestDropId, projectFolderId } from "../../utils/sidebarTree";
import { ContextMenu, useContextMenuState } from "../ContextMenu";
import { SidebarTreeChildren } from "./SidebarTreeChildren";
import { SidebarHoverActions } from "./sidebarTreeShared";

interface GlobalAgentsSectionProps {
  folders: FolderItem[];
  compact: boolean;
  filterQuery: string;
  activeChats: string[];
  onOpenChat: (chat: { id: string; name: string }) => void;
  onDeleteChat: (id: string, name: string) => void;
  onRenameChat: (id: string, name: string) => void;
  onCreate: () => void;
}

/** Open the chat this library agent already has, or create one. Used by Archive, not Global Agents. */
export async function openLibraryAgent(
  profile: AgentProfileDto,
  folders: FolderItem[],
  rootChats: FolderItem["chats"],
  projectSlug: string,
): Promise<{ id: string; name: string } | null> {
  const existing = pickChatForGlobalAgent(chatsInDuckiesTree(folders, rootChats), profile, projectSlug);
  if (existing) return existing;
  const api = getApi();
  if (!api?.create_conversation) return null;
  const config = formToConfig(profileToForm(profile), profile.name, profile.id);
  const created = await api.create_conversation("", profile.ducky_style, undefined, config);
  if (!created?.id) return null;
  return { id: created.id, name: created.title || profile.name };
}

function GlobalChatRow({
  chat,
  active,
  compact,
  onOpen,
  onDelete,
  onRename,
}: {
  chat: FolderItem["chats"][number];
  active: boolean;
  compact: boolean;
  onOpen: () => void;
  onDelete: () => void;
  onRename: () => void;
}) {
  const id = dragId("chat", chat.id);
  const { attributes, listeners, setNodeRef } = useDraggable({ id });
  const context = useContextMenuState<undefined>();
  return (
    <div
      ref={setNodeRef}
      className={["sidebar-tree-row", active ? "is-active" : ""].filter(Boolean).join(" ")}
      aria-label={chat.name}
      data-sidebar-id={id}
      {...attributes}
      {...listeners}
      role="button"
      tabIndex={0}
      onClick={() => onOpen()}
      onContextMenu={(event) => context.open(event, undefined)}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        } else if (event.key === "F2") {
          event.preventDefault();
          event.stopPropagation();
          onRename();
        } else if (event.key === "Delete") {
          event.preventDefault();
          event.stopPropagation();
          onDelete();
        }
      }}
    >
      <span className="sidebar-tree-row-icon sidebar-tree-row-icon--chat">
        <DuckyAvatar styleId={chat.duckyStyle} size={compact ? 22 : DUCKY_AVATAR_SIZES.sidebar} className="ducky-avatar--sidebar" />
      </span>
      <div className="sidebar-tree-row-text"><span className="sidebar-tree-row-label">{chat.name}</span></div>
      <SidebarHoverActions onRename={onRename} onDelete={onDelete} activeChat={active} deleteTitle="Archive" />
      {context.menu ? (
        <ContextMenu
          x={context.menu.x}
          y={context.menu.y}
          onClose={context.close}
          items={[
            { id: "rename", label: "Rename", onClick: onRename },
            { id: "archive", label: "Archive", onClick: onDelete },
          ]}
        />
      ) : null}
    </div>
  );
}

/** Duckies with no island. Templates such as Verse Coder are not rows here. */
export function GlobalAgentsSection({
  folders,
  compact,
  filterQuery,
  activeChats,
  onOpenChat,
  onDeleteChat,
  onRenameChat,
  onCreate,
}: GlobalAgentsSectionProps) {
  const [expanded, setExpanded] = useState(true);
  const { setNodeRef, isOver } = useDroppable({ id: nestDropId(projectFolderId(GLOBAL_PROJECT_SLUG)) });
  const needle = filterQuery.trim().toLowerCase();
  const chats = globalProjectChats(folders).filter((chat) => !needle || chat.name.toLowerCase().includes(needle));
  if (needle && chats.length === 0) return null;

  return (
    <div className={["ducky-tree", "sidebar-global-agents", compact ? "is-compact" : "", isOver ? "sidebar-drop-root-active" : ""].filter(Boolean).join(" ")}>
      <div className={`sidebar-tree-branch ${expanded ? "" : "sidebar-tree-branch-collapsed"}`}>
        <div
          className="sidebar-tree-row"
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setExpanded((open) => !open);
            }
          }}
        >
          <span className="sidebar-folder-leading">
            <span className="chevron-icon" aria-hidden><Icons.ChevronDown /></span>
            <span className="sidebar-tree-row-icon sidebar-tree-row-icon--folder" aria-hidden><Icons.Folder /></span>
          </span>
          <span className="sidebar-tree-row-label">Global Agents</span>
          <button
            type="button"
            className="sidebar-action-btn sidebar-project-add"
            title="Add a ducky with no project"
            onClick={(event) => {
              event.stopPropagation();
              onCreate();
            }}
          >
            <Icons.Plus />
          </button>
        </div>
        <SidebarTreeChildren nestRef={setNodeRef}>
          {chats.length === 0 ? (
            <button type="button" className="sidebar-project-empty" onClick={onCreate}>
              No duckies — add one
            </button>
          ) : chats.map((chat) => (
            <GlobalChatRow
              key={chat.id}
              chat={chat}
              active={activeChats.includes(chat.id)}
              compact={compact}
              onOpen={() => onOpenChat(chat)}
              onDelete={() => onDeleteChat(chat.id, chat.name)}
              onRename={() => onRenameChat(chat.id, chat.name)}
            />
          ))}
        </SidebarTreeChildren>
      </div>
    </div>
  );
}
