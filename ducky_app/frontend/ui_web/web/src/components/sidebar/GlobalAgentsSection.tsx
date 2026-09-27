import { useCallback, useEffect, useState } from "react";
import { DuckyAvatar, DUCKY_AVATAR_SIZES } from "../ducky/DuckyAvatars";
import { formToConfig, profileToForm } from "../ducky/duckyProfileForm";
import { onApiReady } from "../../hooks/onApiReady";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import { onDuckyProfileChanged } from "../../navigation/duckyProfileChanged";
import type { AgentProfileDto, FolderItem } from "../../types/panel";
import { chatsInDuckiesTree, pickChatForGlobalAgent } from "../../utils/globalAgents";
import { SidebarTreeChildren } from "./SidebarTreeChildren";

interface GlobalAgentsSectionProps {
  folders: FolderItem[];
  rootChats: FolderItem["chats"];
  projectSlug: string;
  compact: boolean;
  filterQuery: string;
  activeChats: string[];
  onOpenChat: (chat: { id: string; name: string }) => void;
  onCreated: () => void;
}

export function GlobalAgentsSection({
  folders,
  rootChats,
  projectSlug,
  compact,
  filterQuery,
  activeChats,
  onOpenChat,
  onCreated,
}: GlobalAgentsSectionProps) {
  const [profiles, setProfiles] = useState<AgentProfileDto[]>([]);
  const [expanded, setExpanded] = useState(true);
  const [openingId, setOpeningId] = useState("");

  const reload = useCallback(async () => {
    const api = getApi();
    if (!api?.list_agent_profiles) return;
    const res = await api.list_agent_profiles();
    const listed = (res.profiles ?? []).filter((profile) => profile.id && profile.id !== "__blank__");
    setProfiles(listed);
  }, []);

  useEffect(() => onApiReady(() => { void reload(); }), [reload]);
  useEffect(() => onDuckyProfileChanged(() => { void reload(); }), [reload]);

  const needle = filterQuery.trim().toLowerCase();
  const visible = needle
    ? profiles.filter((profile) => profile.name.toLowerCase().includes(needle))
    : profiles;
  if (visible.length === 0) return null;

  const openProfile = async (profile: AgentProfileDto) => {
    if (openingId) return;
    const existing = pickChatForGlobalAgent(
      chatsInDuckiesTree(folders, rootChats),
      profile,
      projectSlug,
    );
    if (existing) {
      onOpenChat(existing);
      return;
    }
    const api = getApi();
    if (!api?.create_conversation) return;
    setOpeningId(profile.id);
    try {
      const config = formToConfig(profileToForm(profile), profile.name, profile.id);
      const created = await api.create_conversation("", profile.ducky_style, undefined, config);
      if (created?.id) {
        onOpenChat({ id: created.id, name: created.title || profile.name });
        onCreated();
      }
    } finally {
      setOpeningId("");
    }
  };

  const avatarSize = compact ? 22 : DUCKY_AVATAR_SIZES.sidebar;
  const treeChats = chatsInDuckiesTree(folders, rootChats);

  return (
    <div className={["ducky-tree", "sidebar-global-agents", compact ? "is-compact" : ""].filter(Boolean).join(" ")}>
      <div className={`sidebar-tree-branch ${expanded ? "" : "sidebar-tree-branch-collapsed"}`}>
        <div
          className="sidebar-tree-row"
          role="button"
          tabIndex={0}
          onClick={() => setExpanded((open) => !open)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setExpanded((open) => !open);
            }
          }}
        >
          <span className="sidebar-folder-leading">
            <span className="chevron-icon" aria-hidden>
              <Icons.ChevronDown />
            </span>
            <span className="sidebar-tree-row-icon sidebar-tree-row-icon--folder" aria-hidden>
              <Icons.Folder />
            </span>
          </span>
          <span className="sidebar-tree-row-label">Global agents</span>
        </div>
        <SidebarTreeChildren>
          {visible.map((profile) => {
            const open = pickChatForGlobalAgent(treeChats, profile, projectSlug);
            const active = Boolean(open && activeChats.includes(open.id));
            return (
              <div
                key={profile.id}
                className={["sidebar-tree-row", active ? "is-active" : ""].filter(Boolean).join(" ")}
                role="button"
                tabIndex={0}
                title={profile.when_to_use || profile.name}
                onClick={() => void openProfile(profile)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void openProfile(profile);
                  }
                }}
              >
                <span className="sidebar-tree-row-icon sidebar-tree-row-icon--chat">
                  <DuckyAvatar styleId={profile.ducky_style} size={avatarSize} className="ducky-avatar--sidebar" />
                </span>
                <span className="sidebar-tree-row-label">{profile.name}</span>
              </div>
            );
          })}
        </SidebarTreeChildren>
      </div>
    </div>
  );
}
