import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { subscribeAgentEvents } from "../hooks/useAgentEventBus";
import { requestReloadDuckies } from "../hooks/useChatsChanged";
import { getApi } from "../hooks/usePanelApi";
import { useRunningAgents } from "../hooks/useRunningAgents";
import { useWaitingChatIds } from "../hooks/waitingChats";
import { WaitingMarker } from "./WaitingMarker";
import { requestOpenSettings } from "../navigation/openSettingsTab";
import type { AgentProfileDto, ChatTab, ChangesetRunDto, FolderItem, GroupMemberDto, LaneCheckResult } from "../types/panel";
import { conflictCountsByConv } from "../utils/changesetGrouping";
import { fmtCompactTokens } from "../utils/contextFormat";
import { parseLaneText, shortLaneLabel, validateLaneGlobs } from "../utils/laneGlob";
import { findFolderByHubId } from "../utils/folderContextSummary";
import { numberedEntryName } from "../utils/numberedEntryName";
import { chatFolderSiblingNames } from "../utils/sidebarTree";
import { Icons } from "../icons/Icons";
import { DuckyAvatar, DUCKY_AVATAR_SIZES } from "./ducky/DuckyAvatars";
import { useDuckyCatalogOptional } from "./ducky/DuckyCatalogContext";
import { DuckyModelPicker } from "./ducky/DuckyModelPicker";
import { aiTypeLabel, memberFileLines, memberObservationLines } from "./groupMemberHover";
import {
  buildRoster,
  filterRoster,
  rosterAgents,
  rosterGroupIds,
  rosterTokens,
  type RosterNode,
} from "./team/teamRoster";

export { shortModelLabel } from "./groupMemberHover";
export { parseLaneText, shortLaneLabel, validateLaneGlobs } from "../utils/laneGlob";

/** Tooltip for the lane button. */
export function laneTitle(lane: string[] | null | undefined): string {
  const configured = lane == null ? "No write lane configured" : lane.length === 0
    ? "Configured lane: Read-only" : `Configured lane:\n${lane.join("\n")}`;
  return `${configured}\nCurrent enforcement coverage: unknown; native shells are not guaranteed to honor this lane.`;
}

type Props = {
  groupId: string;
  members: GroupMemberDto[];
  /** member_conv_id of the spokesperson. The same star the sidebar draws. */
  leaderConvId?: string;
  /** Sidebar folder tree: nested groups list their agents from it until the bridge answers. */
  folders?: FolderItem[];
  allChats?: ChatTab[];
  onMembersChange: (members: GroupMemberDto[]) => void;
  onOpenMember: (chat: ChatTab) => void;
};

/** Short blurb for the invite list — ~10 words max. */
export function shortWhenToUse(text: string, maxWords = 10): string {
  const words = (text || "").trim().split(/\s+/).filter(Boolean);
  if (words.length <= maxWords) return words.join(" ");
  return `${words.slice(0, maxWords).join(" ")}…`;
}

/** Sidebar duckies that can join this group (not hubs, not already seated, not in another swarm). */
export function inviteableChats(
  allChats: ChatTab[],
  members: GroupMemberDto[],
  groupId: string,
): ChatTab[] {
  const seated = new Set(members.map((m) => m.member_conv_id).filter(Boolean));
  const gid = (groupId || "").trim();
  return allChats
    .filter((c) => {
      if (!c.id || c.id === gid) return false;
      if (c.isGroup) return false;
      if (seated.has(c.id)) return false;
      const parent = (c.parentConvId || "").trim();
      if (parent) return false;
      return true;
    })
    .slice()
    .sort((a, b) => (a.duckyName || a.name || "").localeCompare(b.duckyName || b.name || ""));
}

function isOutside(target: EventTarget | null, root: HTMLElement | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return true;
  if (root?.contains(el)) return false;
  // Model menus portal to body — a pick there is still inside the editor.
  if (el.closest?.(".dropdown-panel")) return false;
  return true;
}

/** Many agents start with their groups folded; a small team shows everyone. */
const AUTO_EXPAND_UP_TO = 12;
/** Avatars on the bar before "+N". */
const BAR_AVATARS = 12;
/** A filter box once the team is this big. */
const FILTER_FROM = 6;

const openKey = (groupId: string) => `ducky.teamRoster.open:${groupId}`;
function readOpen(groupId: string): boolean {
  try {
    return window.localStorage.getItem(openKey(groupId)) === "1";
  } catch {
    return false;
  }
}
function writeOpen(groupId: string, open: boolean): void {
  try {
    if (open) window.localStorage.setItem(openKey(groupId), "1");
    else window.localStorage.removeItem(openKey(groupId));
  } catch {
    /* a remembered pane state only */
  }
}

type Editor = { key: string; kind: "model" | "lane" | "details" };

/**
 * A group chat's team: one compact bar (who is in, who is running or waiting, Add) and,
 * on demand, the roster under it — every agent of every nested group in one table where
 * model and write lane change in place.
 */
export function GroupMemberStrip({
  groupId,
  members,
  leaderConvId = "",
  folders = [],
  allChats = [],
  onMembersChange,
  onOpenMember,
}: Props) {
  const catalog = useDuckyCatalogOptional();
  const labelFor = catalog?.labelFor ?? ((id?: string | null) => id || "Ducky");
  const waitingIds = useWaitingChatIds();
  const runningIds = useRunningAgents();
  const [profiles, setProfiles] = useState<AgentProfileDto[]>([]);
  const [open, setOpen] = useState(() => readOpen(groupId));
  useEffect(() => setOpen(readOpen(groupId)), [groupId]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [laneText, setLaneText] = useState("");
  const [laneCheck, setLaneCheck] = useState<LaneCheckResult | null>(null);
  const [laneSaving, setLaneSaving] = useState(false);
  /** Journal snapshots do not establish current file ownership. */
  const [fileSnapshot, setFileSnapshot] = useState<{ groupId: string; runs: ChangesetRunDto[] | null; readAt: number } | null>(null);
  const fileRequest = useRef(0);
  const scopedFiles = fileSnapshot?.groupId === groupId ? fileSnapshot : null;
  const conflicts = conflictCountsByConv(scopedFiles?.runs || []);
  const [busy, setBusy] = useState(false);
  const [leaderId, setLeaderId] = useState(leaderConvId);
  useEffect(() => setLeaderId(leaderConvId), [leaderConvId]);
  const [error, setError] = useState("");
  /** Nested group id → its members from the bridge (model, lane and observation per agent). */
  const [rosters, setRosters] = useState<Record<string, GroupMemberDto[]>>({});
  const inviteWrapRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const [observedMembers, setObservedMembers] = useState<{ groupId: string; rows: GroupMemberDto[] } | null>(null);
  const [observationNow, setObservationNow] = useState(Date.now());
  const observationRequest = useRef(0);

  const refreshObservations = useCallback(async () => {
    const request = ++observationRequest.current;
    try {
      const result = await getApi()?.group_members?.(groupId);
      if (request !== observationRequest.current) return;
      setObservedMembers({ groupId, rows: result?.ok ? result.members || [] : [] });
    } catch {
      if (request === observationRequest.current) setObservedMembers({ groupId, rows: [] });
    }
    setObservationNow(Date.now());
  }, [groupId]);
  useEffect(() => {
    void refreshObservations();
    const tick = window.setInterval(() => setObservationNow(Date.now()), 15000);
    return () => { observationRequest.current += 1; window.clearInterval(tick); };
  }, [refreshObservations, members]);
  useEffect(() => subscribeAgentEvents(event => {
    const ids = new Set([groupId, ...members.map(m => m.member_conv_id)]);
    if (observedMembers?.groupId === groupId) {
      for (const row of observedMembers.rows) {
        const owner = row.observation?.assignment?.chat_id;
        if (owner) ids.add(owner);
      }
    }
    if (event.conv_id && ids.has(event.conv_id) &&
        ["plan_updated", "plan_assignment_changed", "agent_started", "agent_stopped"].includes(event.type)) {
      void refreshObservations();
    }
  }), [groupId, members, observedMembers, refreshObservations]);

  const refreshProfiles = useCallback(() => {
    const api = getApi();
    if (!api?.list_agent_profiles) return;
    void api.list_agent_profiles().then((res) => {
      setProfiles(Array.isArray(res?.profiles) ? res.profiles : []);
    });
  }, []);
  useEffect(() => {
    refreshProfiles();
  }, [refreshProfiles]);

  const profileById = useMemo(() => {
    const map = new Map<string, AgentProfileDto>();
    for (const p of profiles) if (p.id) map.set(p.id, p);
    return map;
  }, [profiles]);

  const roster = useMemo(
    () => buildRoster({ groupId, members, leaderConvId: leaderId, rosters, folders, allChats, profileById, labelFor }),
    [groupId, members, leaderId, rosters, folders, allChats, profileById, labelFor],
  );

  // Every nested group's roster, as deep as it goes, so all agents can be read and adjusted here.
  const nestedIds = useMemo(() => rosterGroupIds(roster).join("|"), [roster]);
  useEffect(() => {
    const api = getApi();
    const ids = nestedIds ? nestedIds.split("|") : [];
    if (!api?.group_members || ids.length === 0) return;
    let cancelled = false;
    const missing = ids.filter((id) => !rosters[id]);
    if (missing.length === 0) return;
    void Promise.all(
      missing.map(async (id) => {
        try {
          const res = await api.group_members!(id);
          return [id, res?.ok ? res.members || [] : []] as const;
        } catch {
          return [id, []] as const;
        }
      }),
    ).then((rows) => {
      if (cancelled) return;
      setRosters((prev) => {
        const next = { ...prev };
        for (const [id, list] of rows) next[id] = [...list];
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [nestedIds, rosters]);
  // A roster change at this level can move agents between nested groups: read them again.
  const rosterBase = useRef({ members, groupId });
  useEffect(() => {
    if (rosterBase.current.members === members && rosterBase.current.groupId === groupId) return;
    rosterBase.current = { members, groupId };
    setRosters({});
  }, [members, groupId]);

  const agents = useMemo(() => rosterAgents(roster), [roster]);
  const runningCount = agents.filter((a) => runningIds.has(a.id)).length;
  const waitingCount = agents.filter((a) => waitingIds.has(a.id)).length;
  const conflictTotal = agents.reduce((sum, a) => sum + (conflicts[a.id] ?? 0), 0);
  const totalTokens = agents.reduce((sum, a) => sum + a.contextTokens, 0);
  const visible = useMemo(() => filterRoster(roster, query), [roster, query]);
  const isFolded = useCallback(
    (key: string) => (query.trim() ? false : folded[key] ?? agents.length > AUTO_EXPAND_UP_TO),
    [folded, query, agents.length],
  );

  useEffect(() => {
    if (!pickerOpen) return;
    refreshProfiles();
    const onDoc = (e: MouseEvent) => {
      if (isOutside(e.target, inviteWrapRef.current)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [pickerOpen, refreshProfiles]);

  useEffect(() => {
    if (!editor || editor.kind === "details") return;
    const onDoc = (e: MouseEvent) => {
      if (isOutside(e.target, editorRef.current)) setEditor(null);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [editor]);

  const nodeByKey = useMemo(() => {
    const map = new Map<string, RosterNode>();
    const walk = (list: RosterNode[]) => {
      for (const n of list) {
        map.set(n.key, n);
        walk(n.children);
      }
    };
    walk(roster);
    return map;
  }, [roster]);
  const laneNode = editor?.kind === "lane" ? nodeByKey.get(editor.key) : undefined;

  // Lane editor: instant local validation, then the server's overlap verdict (debounced).
  useEffect(() => {
    if (!laneNode) return;
    const lines = parseLaneText(laneText);
    const local = validateLaneGlobs(lines);
    if (local.length > 0) {
      setLaneCheck({ ok: false, errors: local, warnings: [], normalized: null });
      return;
    }
    const api = getApi();
    if (!api?.group_check_lane) return;
    const timer = setTimeout(() => {
      void api.group_check_lane!(laneNode.hubId, laneNode.id, lines).then(setLaneCheck).catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
  }, [laneNode, laneText]);

  const refreshConflicts = useCallback(async () => {
    const request = ++fileRequest.current;
    let runs: ChangesetRunDto[] | null = null;
    try {
      const result = await getApi()?.list_changesets?.("", groupId, 50);
      if (Array.isArray(result)) runs = result.filter(run => run.group_id === groupId);
    } catch { /* Unavailable is not an empty journal. */ }
    if (request === fileRequest.current) setFileSnapshot({ groupId, runs, readAt: Date.now() });
  }, [groupId]);

  useEffect(() => {
    void refreshConflicts();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeAgentEvents((event) => {
      if (event.type !== "file_guard" && event.type !== "agent_stopped" && event.type !== "files_reverted") return;
      if (event.conv_id && event.conv_id !== groupId && !members.some(m => m.member_conv_id === event.conv_id)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void refreshConflicts(), 500);
    });
    return () => {
      fileRequest.current += 1;
      if (timer) clearTimeout(timer);
      unsubscribe();
    };
  }, [refreshConflicts, groupId, members]);

  const invitedIds = useMemo(() => new Set(members.map((m) => m.profile_id).filter(Boolean)), [members]);
  const available = useMemo(
    () => profiles.filter((p) => p.id && !invitedIds.has(p.id)).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [profiles, invitedIds],
  );
  const existingChats = useMemo(() => inviteableChats(allChats, members, groupId), [allChats, members, groupId]);

  /** A roster answer for this group or a nested one: keep each in its own place. */
  const applyRoster = useCallback(
    (hubId: string, next: GroupMemberDto[] | undefined, leader?: string) => {
      if (hubId === groupId) {
        onMembersChange(next || []);
        if (leader !== undefined) setLeaderId(leader || "");
      } else {
        setRosters((prev) => ({ ...prev, [hubId]: next || [] }));
      }
    },
    [groupId, onMembersChange],
  );

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } finally {
      setBusy(false);
    }
  }, []);

  const invite = useCallback(
    (profileId: string) =>
      run(async () => {
        const api = getApi();
        if (!api?.group_invite) return;
        // Profile's own model / Default Model — no per-invite override here.
        const res = await api.group_invite(groupId, profileId);
        if (!res?.ok) {
          setError(res?.error || "Invite failed");
          return;
        }
        applyRoster(groupId, res.group_members, res.leader_conv_id || undefined);
        setPickerOpen(false);
        requestReloadDuckies();
      }),
    [applyRoster, groupId, run],
  );

  const addExisting = useCallback(
    (convId: string) =>
      run(async () => {
        const api = getApi();
        if (!api?.group_add_member) return;
        const res = await api.group_add_member(groupId, convId);
        if (!res?.ok) {
          setError(res?.error || "Invite failed");
          return;
        }
        applyRoster(groupId, res.group_members, res.leader_conv_id || undefined);
        setPickerOpen(false);
        requestReloadDuckies();
      }),
    [applyRoster, groupId, run],
  );

  const createNestedGroup = useCallback(
    () =>
      run(async () => {
        const api = getApi();
        if (!api?.group_create) return;
        const parentFolder = findFolderByHubId(folders, groupId);
        const parentId = (parentFolder?.id || "").trim();
        if (!parentId) {
          setError("This group has no folder — create a nested group from the sidebar");
          return;
        }
        const name = numberedEntryName("Group", chatFolderSiblingNames(folders, parentId));
        const res = await api.group_create(name, parentId);
        if (!res?.ok || !res.id) {
          setError(res?.error || "Could not create group");
          return;
        }
        // Sync the roster so the new nested group shows up.
        const latest = api.group_members ? await api.group_members(groupId) : null;
        if (latest?.ok) onMembersChange(latest.members || []);
        setPickerOpen(false);
        requestReloadDuckies();
        onOpenMember({ id: res.id, name: (res.title || name).trim() || "Group", isGroup: true, groupMembers: res.group_members || [] });
      }),
    [folders, groupId, onMembersChange, onOpenMember, run],
  );

  const setMemberModel = useCallback(
    (node: RosterNode, model: string) =>
      run(async () => {
        const api = getApi();
        if (!api?.group_set_member_model) return;
        const res = await api.group_set_member_model(node.hubId, node.id, model);
        if (!res?.ok) {
          setError(res?.error || "Could not set model");
          return;
        }
        applyRoster(node.hubId, res.group_members);
      }),
    [applyRoster, run],
  );

  const openLaneEditor = useCallback((node: RosterNode) => {
    setEditor({ key: node.key, kind: "lane" });
    setLaneText((node.member?.write_allowed ?? []).join("\n"));
    setLaneCheck(null);
    setError("");
  }, []);

  const saveLane = useCallback(
    async (node: RosterNode, lane: string[] | null, force = false) => {
      const api = getApi();
      if (!api?.group_set_member_lane) return;
      setLaneSaving(true);
      setError("");
      try {
        const res = await api.group_set_member_lane(node.hubId, node.id, lane, force);
        if (!res?.ok) {
          setError(res?.error || "Could not set lane");
          return;
        }
        applyRoster(node.hubId, res.group_members);
        setEditor(null);
      } finally {
        setLaneSaving(false);
      }
    },
    [applyRoster],
  );

  const remove = useCallback(
    (node: RosterNode) =>
      run(async () => {
        const api = getApi();
        if (!api?.group_remove) return;
        const res = await api.group_remove(node.hubId, node.id);
        if (!res?.ok) {
          setError(res?.error || "Remove failed");
          return;
        }
        applyRoster(node.hubId, res.group_members, node.hubId === groupId ? res.leader_conv_id ?? "" : undefined);
        if (editor?.key === node.key) setEditor(null);
        requestReloadDuckies();
      }),
    [applyRoster, editor, groupId, run],
  );

  const openNode = useCallback(
    (node: RosterNode) => {
      if (node.isGroup) {
        onOpenMember({ id: node.id, name: node.name, isGroup: true });
        return;
      }
      const profile = node.member ? profileById.get(node.member.profile_id) : undefined;
      onOpenMember({
        id: node.id,
        name: node.name,
        duckyName: node.name,
        duckyStyle: node.styleId,
        duckyPersonality: profile?.ducky_personality,
        ttsVoice: node.member?.tts_voice || profile?.tts_voice,
        ttsSpeed: node.member?.tts_speed ?? profile?.tts_speed,
        model: node.model,
        codingAgent: node.codingAgent,
        parentConvId: node.hubId,
      });
    },
    [onOpenMember, profileById],
  );

  const toggleOpen = useCallback(() => {
    setOpen((was) => {
      writeOpen(groupId, !was);
      return !was;
    });
  }, [groupId]);

  /** The member row the bridge last observed (this group's or a nested group's roster). */
  const observed = (node: RosterNode): GroupMemberDto | undefined => {
    if (node.hubId === groupId) {
      return observedMembers?.groupId === groupId
        ? observedMembers.rows.find((row) => row.member_conv_id === node.id)
        : undefined;
    }
    return rosters[node.hubId]?.find((row) => row.member_conv_id === node.id);
  };

  const statusOf = (node: RosterNode): { label: string; cls: string } => {
    if (node.isGroup) {
      const inside = rosterAgents(node.children);
      const running = inside.filter((a) => runningIds.has(a.id)).length;
      const waiting = inside.filter((a) => waitingIds.has(a.id)).length;
      if (waiting) return { label: `${waiting} waiting`, cls: "waiting" };
      if (running) return { label: `${running} running`, cls: "running" };
      return { label: `${inside.length} ${inside.length === 1 ? "agent" : "agents"}`, cls: "idle" };
    }
    if (waitingIds.has(node.id)) return { label: "Waiting", cls: "waiting" };
    if (runningIds.has(node.id)) return { label: "Running", cls: "running" };
    return { label: "Idle", cls: "idle" };
  };

  const renderEditor = (node: RosterNode) => {
    if (!editor || editor.key !== node.key) return null;
    if (editor.kind === "model") {
      return (
        <div className="team-roster-editor" ref={editorRef} style={{ ["--depth" as string]: node.depth }}>
          <div className="team-roster-editor-label">Model for {node.name}</div>
          <DuckyModelPicker
            model={node.model}
            onChange={(next) => void setMemberModel(node, next)}
            variant="chips"
            label=""
            hint=""
            allowClear
            placeholder="Default model"
            menuPlacement="bottom"
          />
        </div>
      );
    }
    if (editor.kind === "lane") {
      return (
        <div className="team-roster-editor" ref={editorRef} style={{ ["--depth" as string]: node.depth }}>
          <div className="team-roster-editor-label">Write lane for {node.name}</div>
          <textarea
            className="group-member-lane-textarea"
            value={laneText}
            onChange={(e) => setLaneText(e.target.value)}
            placeholder={"Content/Verse/Shop/**\nContent/Verse/module_declarations.verse"}
            spellCheck={false}
            aria-label={`Write lane for ${node.name}`}
          />
          <div className="group-member-lane-hint">
            One glob per line; a bare folder means folder/**. Save with no lines = configured read-only. Clear = no configured restriction. Enforcement coverage is unknown; native shells may bypass lanes.
          </div>
          {laneCheck?.errors.length ? (
            <ul className="group-member-lane-problems group-member-lane-problems--error">
              {laneCheck.errors.map((t) => <li key={t}>{t}</li>)}
            </ul>
          ) : null}
          {laneCheck?.warnings.length ? (
            <ul className="group-member-lane-problems group-member-lane-problems--warning">
              {laneCheck.warnings.map((t) => <li key={t}>{t}</li>)}
            </ul>
          ) : null}
          <div className="group-member-lane-actions">
            <button
              type="button"
              className="group-member-lane-btn group-member-lane-btn--primary"
              disabled={laneSaving || Boolean(laneCheck?.errors.length)}
              onClick={() => void saveLane(node, parseLaneText(laneText), Boolean(laneCheck?.warnings.length))}
            >
              {laneCheck?.warnings.length ? "Save anyway" : "Save"}
            </button>
            <button type="button" className="group-member-lane-btn" disabled={laneSaving} onClick={() => void saveLane(node, null)}>
              Clear lane
            </button>
            <button type="button" className="group-member-lane-btn" onClick={() => setEditor(null)}>
              Cancel
            </button>
          </div>
        </div>
      );
    }
    const member = node.member;
    const lines = member
      ? [
          ...memberObservationLines({ ...member, observation: observed(node)?.observation }, node.hubId, observationNow),
          ...memberFileLines(scopedFiles?.runs ?? null, node.id, scopedFiles?.readAt ?? 0, observationNow),
        ]
      : ["Runtime: unknown", "Assignment: unknown"];
    return (
      <div className="team-roster-details" style={{ ["--depth" as string]: node.depth }}>
        {node.blurb ? <div className="team-roster-details-blurb">{shortWhenToUse(node.blurb, 24)}</div> : null}
        <div className="team-roster-details-ai">{aiTypeLabel(node.model, node.codingAgent)}</div>
        <ul className="team-roster-details-lines">
          {lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <button
          type="button"
          className="group-member-lane-btn"
          onClick={() => { void refreshObservations(); void refreshConflicts(); setRosters({}); }}
        >
          Refresh observation
        </button>
      </div>
    );
  };

  const renderRow = (node: RosterNode): ReactElement => {
    const status = statusOf(node);
    const waiting = !node.isGroup && waitingIds.has(node.id);
    const conflictCount = node.isGroup ? 0 : conflicts[node.id] ?? 0;
    const lane = node.member?.write_allowed;
    const laneKind = lane == null ? "none" : lane.length === 0 ? "readonly" : "set";
    const editable = Boolean(node.member) && !node.isGroup;
    const foldedNow = node.isGroup && isFolded(node.key);
    return (
      <Fragment key={node.key}>
        <div
          className={`team-roster-row${node.isGroup ? " team-roster-row--group" : ""}`}
          style={{ ["--depth" as string]: node.depth }}
          role="row"
        >
          <span className="team-roster-cell team-roster-cell--name" role="cell">
            {node.isGroup ? (
              <button
                type="button"
                className="team-roster-fold"
                aria-expanded={!foldedNow}
                aria-label={`${foldedNow ? "Show" : "Hide"} ${node.name}'s agents`}
                onClick={() => setFolded((prev) => ({ ...prev, [node.key]: !foldedNow }))}
              >
                {foldedNow ? <Icons.ChevronRight /> : <Icons.ChevronDown />}
              </button>
            ) : (
              <span className="team-roster-fold team-roster-fold--leaf" aria-hidden />
            )}
            <button
              type="button"
              className="team-roster-open"
              disabled={busy}
              onClick={() => openNode(node)}
              title={node.isGroup ? `Open group ${node.name}` : `Open ${node.name}'s work`}
            >
              <span className="team-avatar" style={{ ["--member-color" as string]: node.color || "transparent" }}>
                {node.isGroup ? (
                  <span className="team-avatar-group" aria-hidden><Icons.Users /></span>
                ) : (
                  <DuckyAvatar styleId={node.styleId} size={DUCKY_AVATAR_SIZES.compact} title={node.name} />
                )}
                {node.isLeader ? (
                  <span className="sidebar-leader-badge" title="Group leader" aria-label="Group leader"><Icons.Star /></span>
                ) : null}
              </span>
              <span className="team-roster-name">{node.name}</span>
              {waiting ? <WaitingMarker convId={node.id} variant="chip" interactive={false} /> : null}
            </button>
          </span>
          <span className={`team-roster-cell team-roster-status team-roster-status--${status.cls}`} role="cell">
            {status.label}
          </span>
          <span className="team-roster-cell" role="cell">
            {editable ? (
              <button
                type="button"
                className="team-roster-pick"
                disabled={busy}
                title={`Change ${node.name}'s model`}
                onClick={() => setEditor(editor?.key === node.key && editor.kind === "model" ? null : { key: node.key, kind: "model" })}
              >
                <span className="team-roster-pick-text">{aiTypeLabel(node.model, node.codingAgent)}</span>
                <Icons.ChevronDown />
              </button>
            ) : !node.isGroup ? (
              <span className="team-roster-muted">{aiTypeLabel(node.model, node.codingAgent)}</span>
            ) : null}
          </span>
          <span className="team-roster-cell" role="cell">
            {editable ? (
              <button
                type="button"
                className={`team-roster-pick team-roster-lane team-roster-lane--${laneKind}`}
                disabled={busy}
                title={laneTitle(lane)}
                onClick={() => (editor?.key === node.key && editor.kind === "lane" ? setEditor(null) : openLaneEditor(node))}
              >
                <span className="team-roster-pick-text">{shortLaneLabel(lane)}</span>
                <Icons.ChevronDown />
              </button>
            ) : null}
          </span>
          <span className="team-roster-cell team-roster-tokens" role="cell" title="Context">
            {fmtCompactTokens(rosterTokens(node))}
            {conflictCount > 0 ? (
              <span
                className="group-member-chip-conflict"
                title={`${conflictCount} recorded file conflict${conflictCount === 1 ? "" : "s"} in runs reported running${observationNow - (scopedFiles?.readAt ?? 0) > 60000 ? " (stale snapshot)" : ""} — see Context → Files`}
              />
            ) : null}
          </span>
          <span className="team-roster-cell team-roster-actions" role="cell">
            {!node.isGroup ? (
              <button
                type="button"
                className="team-roster-icon"
                aria-label={`Details for ${node.name}`}
                aria-expanded={editor?.key === node.key && editor.kind === "details"}
                title="Details"
                onClick={() => setEditor(editor?.key === node.key && editor.kind === "details" ? null : { key: node.key, kind: "details" })}
              >
                i
              </button>
            ) : null}
            {node.member ? (
              <button
                type="button"
                className="team-roster-icon team-roster-icon--remove"
                aria-label={`Remove ${node.name}`}
                title={`Remove ${node.name}`}
                disabled={busy}
                onClick={() => void remove(node)}
              >
                ×
              </button>
            ) : null}
          </span>
        </div>
        {renderEditor(node)}
        {node.isGroup && !foldedNow ? node.children.map(renderRow) : null}
      </Fragment>
    );
  };

  const barAgents = agents.slice(0, BAR_AVATARS);
  const more = agents.length - barAgents.length;
  const groupCount = rosterGroupIds(roster).length;

  return (
    <div className={`team-bar-wrap${open ? " is-open" : ""}`}>
      <div className="team-bar">
        <button
          type="button"
          className="team-bar-toggle"
          aria-expanded={open}
          aria-controls={`team-roster-${groupId}`}
          title={open ? "Hide the team" : "Show the team: model, write lane and context of every agent"}
          onClick={toggleOpen}
        >
          <span className="team-bar-icon" aria-hidden><Icons.Users /></span>
          <span className="team-bar-title">Team</span>
          <span className="team-bar-count">
            {agents.length} {agents.length === 1 ? "agent" : "agents"}
            {groupCount ? ` · ${groupCount} ${groupCount === 1 ? "group" : "groups"}` : ""}
          </span>
          {runningCount ? <span className="team-bar-stat team-bar-stat--running">{runningCount} running</span> : null}
          {waitingCount ? <span className="team-bar-stat team-bar-stat--waiting">{waitingCount} waiting</span> : null}
          {conflictTotal ? (
            <span className="team-bar-stat team-bar-stat--conflict">
              {conflictTotal} file {conflictTotal === 1 ? "conflict" : "conflicts"}
            </span>
          ) : null}
          <span className="team-bar-chevron" aria-hidden>{open ? <Icons.ChevronDown /> : <Icons.ChevronRight />}</span>
        </button>
        <div className="team-bar-avatars" aria-label="Agents">
          {barAgents.map((a) => {
            const state = waitingIds.has(a.id) ? "waiting" : runningIds.has(a.id) ? "running" : "idle";
            return (
              <button
                key={a.key}
                type="button"
                className={`team-bar-avatar team-bar-avatar--${state}`}
                title={`${a.name} · ${aiTypeLabel(a.model, a.codingAgent)} · ${fmtCompactTokens(a.contextTokens)}${state === "idle" ? "" : ` · ${state}`}`}
                aria-label={`Open ${a.name}`}
                onClick={() => openNode(a)}
              >
                <DuckyAvatar styleId={a.styleId} size={DUCKY_AVATAR_SIZES.compact} />
                {a.isLeader ? <span className="sidebar-leader-badge" aria-hidden><Icons.Star /></span> : null}
              </button>
            );
          })}
          {more > 0 ? (
            <button type="button" className="team-bar-more" onClick={() => { if (!open) toggleOpen(); }} title="Show every agent">
              +{more}
            </button>
          ) : null}
        </div>
        <div className="group-member-invite-wrap" ref={inviteWrapRef}>
          <button
            type="button"
            className="group-member-invite-btn"
            disabled={busy}
            onClick={() => {
              setEditor(null);
              setPickerOpen((v) => !v);
            }}
          >
            <Icons.Plus /> Add
          </button>
          {pickerOpen ? (
            <div className="group-member-picker" role="listbox">
              <button type="button" className="group-member-picker-item group-member-picker-create" disabled={busy} onClick={() => void createNestedGroup()}>
                <span className="group-member-picker-create-icon" aria-hidden><Icons.Users /></span>
                <span className="group-member-picker-meta">
                  <span className="group-member-picker-name">New group</span>
                  <span className="group-member-picker-when">Nest a subgroup here — invite duckies into it next</span>
                </span>
              </button>
              <button
                type="button"
                className="group-member-picker-item group-member-picker-create"
                disabled={busy}
                onClick={() => {
                  setPickerOpen(false);
                  requestOpenSettings("Duckies", { newDucky: true });
                }}
              >
                <span className="group-member-picker-create-icon" aria-hidden>+</span>
                <span className="group-member-picker-meta">
                  <span className="group-member-picker-name">New ducky</span>
                  <span className="group-member-picker-when">Add a ducky in Settings, then invite them here</span>
                </span>
              </button>
              {existingChats.length === 0 && available.length === 0 ? (
                <div className="group-member-picker-empty">
                  {profiles.length === 0 ? "No duckies yet — create one above" : "Everyone is already in"}
                </div>
              ) : (
                <>
                  {existingChats.map((c) => {
                    const duckyName = (c.duckyName || c.name || "").trim() || labelFor(c.duckyStyle);
                    return (
                      <button key={c.id} type="button" className="group-member-picker-item group-member-picker-invite" disabled={busy} onClick={() => void addExisting(c.id)} title={duckyName}>
                        <DuckyAvatar styleId={c.duckyStyle} size={DUCKY_AVATAR_SIZES.compact} title={duckyName} className="group-member-picker-avatar" />
                        <span className="group-member-picker-meta">
                          <span className="group-member-picker-name">{duckyName}</span>
                          <span className="group-member-picker-when">Add this ducky</span>
                        </span>
                      </button>
                    );
                  })}
                  {available.map((p) => {
                    const duckyName = (p.name || "").trim() || labelFor(p.ducky_style);
                    return (
                      <button key={p.id} type="button" className="group-member-picker-item group-member-picker-invite" disabled={busy} onClick={() => void invite(p.id)} title={p.when_to_use || p.name}>
                        <DuckyAvatar styleId={p.ducky_style} size={DUCKY_AVATAR_SIZES.compact} title={duckyName} className="group-member-picker-avatar" />
                        <span className="group-member-picker-meta">
                          <span className="group-member-picker-name">{duckyName}</span>
                          <span className="group-member-picker-when">{shortWhenToUse(p.when_to_use || p.ducky_personality || "", 10)}</span>
                        </span>
                      </button>
                    );
                  })}
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
      {open ? (
        <div className="team-roster" id={`team-roster-${groupId}`}>
          <div className="team-roster-tools">
            <span className="team-roster-summary">Total context {fmtCompactTokens(totalTokens)}</span>
            {agents.length >= FILTER_FROM ? (
              <label className="team-roster-filter">
                <Icons.Search />
                <input
                  type="search"
                  value={query}
                  placeholder="Filter by name or model"
                  aria-label="Filter agents"
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
            ) : null}
            {groupCount ? (
              <>
                <button
                  type="button"
                  className="team-roster-tool"
                  onClick={() => setFolded(Object.fromEntries(rosterGroupIdsWithKeys(roster).map((k) => [k, false])))}
                >
                  Expand all
                </button>
                <button
                  type="button"
                  className="team-roster-tool"
                  onClick={() => setFolded(Object.fromEntries(rosterGroupIdsWithKeys(roster).map((k) => [k, true])))}
                >
                  Collapse all
                </button>
              </>
            ) : null}
          </div>
          {members.length === 0 ? (
            <div className="team-roster-empty">No one here yet. Add duckies or a nested group.</div>
          ) : (
            <div className="team-roster-table" role="table" aria-label="Team">
              <div className="team-roster-row team-roster-row--head" role="row">
                <span className="team-roster-cell" role="columnheader">Agent</span>
                <span className="team-roster-cell" role="columnheader">Status</span>
                <span className="team-roster-cell" role="columnheader">Model</span>
                <span className="team-roster-cell" role="columnheader">Write lane</span>
                <span className="team-roster-cell team-roster-tokens" role="columnheader">Context</span>
                <span className="team-roster-cell" role="columnheader" aria-label="Actions" />
              </div>
              {visible.length === 0 ? (
                <div className="team-roster-empty">No agent matches “{query.trim()}”.</div>
              ) : (
                visible.map(renderRow)
              )}
            </div>
          )}
        </div>
      ) : null}
      {error ? <div className="group-member-strip-error" role="alert">{error}</div> : null}
    </div>
  );
}

/** Every group row's key in the tree (for Expand all / Collapse all). */
function rosterGroupIdsWithKeys(nodes: RosterNode[]): string[] {
  const out: string[] = [];
  const walk = (list: RosterNode[]) => {
    for (const n of list) {
      if (!n.isGroup) continue;
      out.push(n.key);
      walk(n.children);
    }
  };
  walk(nodes);
  return out;
}
