import { useCallback, useEffect, useRef, useState } from "react";
import { DuckyAvatar, DUCKY_AVATAR_SIZES } from "../ducky/DuckyAvatars";
import { formToConfig, profileToForm } from "../ducky/duckyProfileForm";
import { useConfirmModal } from "../../contexts/ConfirmModalContext";
import { rememberAgentProfilesList } from "../../hooks/agentProfilesCache";
import { onApiReady } from "../../hooks/onApiReady";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import { emitDuckyProfileChanged, onDuckyProfileChanged } from "../../navigation/duckyProfileChanged";
import type { AgentProfileDto, FolderItem } from "../../types/panel";
import { chatsInDuckiesTree, pickChatForGlobalAgent } from "../../utils/globalAgents";
import { AppNotice } from "../AppNotice";
import { ContextMenu, useContextMenuState } from "../ContextMenu";
import { SidebarTreeChildren } from "./SidebarTreeChildren";
import { SidebarHoverActions } from "./sidebarTreeShared";

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

type Rename = { profile: AgentProfileDto; value: string };

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
  const { confirm, alert } = useConfirmModal();
  const [profiles, setProfiles] = useState<AgentProfileDto[]>([]);
  const [expanded, setExpanded] = useState(true);
  const [openingId, setOpeningId] = useState("");
  const [busyId, setBusyId] = useState("");
  const [editing, setEditing] = useState<Rename | null>(null);
  const [loadError, setLoadError] = useState("");
  const editingRef = useRef<Rename | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const mutatingRef = useRef(false);
  const loadVersion = useRef(0);
  const context = useContextMenuState<AgentProfileDto>();

  const reload = useCallback(async () => {
    const api = getApi();
    if (!api?.list_agent_profiles) return;
    const version = ++loadVersion.current;
    try {
      const res = await api.list_agent_profiles();
      if (version !== loadVersion.current) return;
      rememberAgentProfilesList({ profiles: res.profiles ?? [], templateProfiles: res.template_profiles, blankProfileId: res.blank_profile_id });
      setProfiles((res.profiles ?? []).filter((profile) => profile.id && profile.id !== "__blank__"));
      setLoadError("");
    } catch {
      if (version === loadVersion.current) setLoadError("Failed to refresh global agents.");
    }
  }, []);

  useEffect(() => onApiReady(() => { void reload(); }), [reload]);
  useEffect(() => onDuckyProfileChanged(() => { void reload(); }), [reload]);
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing?.profile.id]);

  const beginRename = (profile: AgentProfileDto) => {
    if (mutatingRef.current) return;
    const next = { profile, value: profile.name };
    editingRef.current = next;
    setEditing(next);
  };

  const cancelRename = () => {
    editingRef.current = null;
    setEditing(null);
  };

  const commitRename = async () => {
    const pending = editingRef.current;
    // Clear synchronously so Enter followed by blur cannot save twice.
    cancelRename();
    if (!pending || mutatingRef.current) return;
    const { profile } = pending;
    const name = pending.value.trim();
    if (!name || name === profile.name) return;
    mutatingRef.current = true;
    setBusyId(profile.id);
    try {
      const api = getApi();
      if (!api) throw new Error("The app is still connecting. Please try again.");
      const result = profile.kind === "bundled"
        ? await api.save_agent_profile_override(profile.id, { name })
        : await api.save_agent_profile({ ...profile, name });
      if (!result.ok) throw new Error("The name could not be saved. Please try again.");
      ++loadVersion.current;
      setProfiles((items) => items.map((item) => item.id === profile.id ? result.profile : item));
      emitDuckyProfileChanged({ type: "saved", profileId: profile.id, name: result.profile.name, duckyStyle: result.profile.ducky_style });
    } catch (error) {
      await alert({ title: "Rename failed", message: error instanceof Error ? error.message : "The name could not be saved." });
    } finally {
      mutatingRef.current = false;
      setBusyId("");
    }
  };

  const deleteProfile = async (profile: AgentProfileDto) => {
    if (mutatingRef.current) return;
    mutatingRef.current = true;
    setBusyId(profile.id);
    try {
      const bundled = profile.kind === "bundled";
      const accepted = await confirm({
        title: "Delete global agent",
        message: bundled
          ? `Remove "${profile.name}" from Global agents? Existing chats will be kept, and this template will still be available when creating an agent.`
          : `Delete "${profile.name}" from Global agents? This custom profile cannot be recovered. Existing chats will be kept.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (accepted !== true) return;
      const api = getApi();
      if (!api) throw new Error("The app is still connecting. Please try again.");
      const result = await api.delete_agent_profile(profile.id);
      if (!result.ok) throw new Error("The agent could not be deleted. Please try again.");
      ++loadVersion.current;
      setProfiles((items) => items.filter((item) => item.id !== profile.id));
      emitDuckyProfileChanged({ type: "deleted", profileId: profile.id });
    } catch (error) {
      await alert({ title: "Delete failed", message: error instanceof Error ? error.message : "The agent could not be deleted." });
    } finally {
      mutatingRef.current = false;
      setBusyId("");
    }
  };

  const needle = filterQuery.trim().toLowerCase();
  const visible = needle
    ? profiles.filter((profile) => profile.name.toLowerCase().includes(needle))
    : profiles;
  if (visible.length === 0 && !loadError) return null;

  const openProfile = async (profile: AgentProfileDto) => {
    if (openingId || editingRef.current || mutatingRef.current) return;
    const existing = pickChatForGlobalAgent(chatsInDuckiesTree(folders, rootChats), profile, projectSlug);
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
      <AppNotice message={loadError} />
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
          <span className="sidebar-tree-row-label">Global agents</span>
        </div>
        <SidebarTreeChildren>
          {visible.map((profile) => {
            const open = pickChatForGlobalAgent(treeChats, profile, projectSlug);
            const active = Boolean(open && activeChats.includes(open.id));
            const isEditing = editing?.profile.id === profile.id;
            return (
              <div
                key={profile.id}
                className={["sidebar-tree-row", active ? "is-active" : ""].filter(Boolean).join(" ")}
                role="button"
                tabIndex={0}
                aria-label={profile.name}
                aria-busy={busyId === profile.id}
                title={profile.when_to_use || profile.name}
                onClick={() => void openProfile(profile)}
                onContextMenu={(event) => { if (!isEditing && !busyId) context.open(event, profile); }}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget || isEditing) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void openProfile(profile);
                  } else if (event.key === "F2") {
                    event.preventDefault();
                    event.stopPropagation();
                    beginRename(profile);
                  } else if (event.key === "Delete") {
                    event.preventDefault();
                    event.stopPropagation();
                    void deleteProfile(profile);
                  }
                }}
              >
                <span className="sidebar-tree-row-icon sidebar-tree-row-icon--chat">
                  <DuckyAvatar styleId={profile.ducky_style} size={avatarSize} className="ducky-avatar--sidebar" />
                </span>
                {isEditing ? (
                  <input
                    ref={inputRef}
                    className="sidebar-rename-input"
                    aria-label={`Rename ${profile.name}`}
                    value={editing.value}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      const next = { profile, value: event.target.value };
                      editingRef.current = next;
                      setEditing(next);
                    }}
                    onBlur={() => void commitRename()}
                    onKeyDown={(event) => {
                      event.stopPropagation();
                      if (event.nativeEvent.isComposing) return;
                      if (event.key === "Enter") { event.preventDefault(); void commitRename(); }
                      if (event.key === "Escape") { event.preventDefault(); cancelRename(); }
                    }}
                  />
                ) : (
                  <div className="sidebar-tree-row-text"><span className="sidebar-tree-row-label">{profile.name}</span></div>
                )}
                {!isEditing && !busyId ? (
                  <SidebarHoverActions onRename={() => beginRename(profile)} onDelete={() => void deleteProfile(profile)} activeChat={active} />
                ) : null}
              </div>
            );
          })}
        </SidebarTreeChildren>
      </div>
      {context.menu ? (
        <ContextMenu x={context.menu.x} y={context.menu.y} onClose={context.close} items={[
          { id: "rename", label: "Rename", onClick: () => beginRename(context.menu!.data) },
          { id: "delete", label: "Delete", danger: true, onClick: () => void deleteProfile(context.menu!.data) },
        ]} />
      ) : null}
    </div>
  );
}
