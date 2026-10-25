import { useEffect, useState, useRef } from "react";
import type { AgentEvent, ChatPlan, GroupMemberDto, PlanNode } from "../types/panel";
import { getApi } from "../hooks/usePanelApi";
import { subscribeAgentEvents } from "../hooks/useAgentEventBus";
import { useRunningAgents } from "../hooks/useRunningAgents";
import { getChatTurnTimer } from "../hooks/chatTurnTimer";
import { getCachedChatMessages } from "../hooks/chatMessagesCache";
import { agentStepText, buildActivityLines, activityPanelTitle, splitTurnMessages } from "../utils/agentActivity";
import { requestOpenChatTab } from "../navigation/openChatReference";
import { requestLatestChatActivity } from "../navigation/latestChatActivity";
import { requestOpenPlanTab } from "../navigation/openPlanTab";
import { findNodePath } from "../utils/planOutlineNav";
import { DuckyAvatar } from "./ducky/DuckyAvatars";
import { useRoster } from "./team/rosterStore";
import "./PlanOwnerChips.css";

type Owner = { id: string; name: string; style?: string; members?: GroupMemberDto[] };
let cachedApi: ReturnType<typeof getApi>;
let directory: Promise<Owner[]> | undefined;
let profileList: Promise<Owner[]> | undefined;
function owners(): Promise<Owner[]> {
  const api = getApi();
  if (cachedApi !== api) { cachedApi = api; directory = undefined; profileList = undefined; }
  return directory ??= (api?.list_all_conversations?.(true) ?? Promise.resolve([])).then(rows => rows.map(row => ({
    id: row.id, name: row.title || row.ducky_name || row.id, style: row.ducky_style,
    members: row.is_group ? row.group_members || [] : undefined,
  }))).catch(() => { directory = undefined; return []; });
}

function profiles(): Promise<Owner[]> {
  void owners();
  return profileList ??= (getApi()?.list_agent_profiles?.() ?? Promise.resolve({ profiles: [] })).then(res => (res?.profiles || []).map(p => ({
    id: p.id, name: p.name || p.id, style: p.ducky_style,
  }))).catch(() => { profileList = undefined; return []; });
}

/** A planned owner is a chat id or a ducky profile id. */
async function resolveOwner(id: string, retry = true): Promise<Owner> {
  const found = (await owners()).find(row => row.id === id) || (await profiles()).find(row => row.id === id);
  if (found || !retry) return found || { id, name: id };
  // Not in the cached lists: a chat or profile made since; read them once more.
  directory = undefined; profileList = undefined;
  return resolveOwner(id, false);
}

/** Assign picker: members of the lead's groups first, then ducky profiles. */
export async function assignChoices(leadId: string): Promise<Owner[]> {
  const seen = new Set<string>([leadId]);
  const members: Owner[] = [];
  for (const row of await owners()) {
    if (!row.members?.some(m => m.member_conv_id === leadId)) continue;
    for (const m of row.members) {
      if (seen.has(m.member_conv_id)) continue;
      seen.add(m.member_conv_id);
      members.push({ id: m.member_conv_id, name: m.name || m.ducky_name || m.member_conv_id, style: m.ducky_style });
    }
  }
  return [...members, ...(await profiles())];
}

type AssignApi = {
  plan_set_planned_assignee?: (chatId: string, nodeId: string, who: string) => Promise<{ ok?: boolean; error?: string }>;
};

/** A sub plan without an agent: its planned owner (dimmed, "planned") or Assign. Picking never starts anyone. */
export function PlanAssignChip({ chatId, nodeId, planned, readOnly = false }: { chatId: string; nodeId: string; planned?: string; readOnly?: boolean }) {
  const [who, setWho] = useState(planned || "");
  useEffect(() => setWho(planned || ""), [planned]);
  const [shown, setShown] = useState<Owner | null>(null);
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState<Owner[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!who) return;
    let alive = true;
    void resolveOwner(who).then(found => { if (alive) setShown(found); });
    return () => { alive = false; };
  }, [who]);
  const toggle = () => {
    if (readOnly) return;
    if (!open) {
      // The picker lists the roster and profiles as they are now.
      directory = undefined; profileList = undefined;
      void assignChoices(chatId).then(setChoices);
    }
    setOpen(!open);
  };
  const pick = async (id: string) => {
    setOpen(false);
    const call = (getApi() as unknown as AssignApi | null)?.plan_set_planned_assignee;
    if (!call) return;
    const res = await call(chatId, nodeId, id).catch((err: unknown) => ({ ok: false, error: String(err) }));
    if (res?.ok === false) { setError(res.error || "Could not assign"); return; }
    setError("");
    setWho(id);
  };
  const name = shown?.id === who ? shown.name : who;
  return <div className="plan-owner-chips plan-assign">
    <button type="button" className={`plan-owner-chip ${who ? "plan-owner-chip--planned" : "plan-assign-chip"}`} onClick={toggle}
      aria-expanded={open} disabled={readOnly} title={who ? `Planned owner: ${name}` : "Pick who works on this sub plan"}>
      {who ? <><DuckyAvatar styleId={shown?.style} size={20} /><span>{name}</span><span className="plan-owner-activity">planned</span></> : "Assign"}
    </button>
    {open ? <div className="plan-assign-menu" role="menu">
      {choices.map(choice => <button key={choice.id} type="button" role="menuitem" className="plan-assign-item" onClick={() => void pick(choice.id)}>
        <DuckyAvatar styleId={choice.style} size={18} /><span>{choice.name}</span>
      </button>)}
      {who ? <button type="button" role="menuitem" className="plan-assign-item" onClick={() => void pick("")}>Remove</button> : null}
    </div> : null}
    {error ? <span className="plan-assign-error" role="alert">{error}</span> : null}
  </div>;
}

export function ownerActivity(event: AgentEvent): string | undefined {
  if (event.type === "agent_stopped" || event.type === "error") return "Idle";
  return agentStepText(event);
}

export function PlanOwnerChips({ ownerId, activeOnly = false, nodeId }: { ownerId: string; activeOnly?: boolean; nodeId?: string }) {
  const [owner, setOwner] = useState<Owner>({ id: ownerId, name: ownerId });
  const tracked = useRef(new Set([ownerId]));
  const waiting = useRef(new Map<string, Set<string>>());
  const [activity, setActivity] = useState<Record<string, string>>({});
  const [now, setNow] = useState(Date.now());
  const running = useRunningAgents();
  // Group members come from the shared roster store: one group_members call per group for every chip.
  const roster = useRoster(owner.members !== undefined ? ownerId : "");
  const members = roster?.members.length ? roster.members : owner.members;
  tracked.current = new Set([ownerId, ...(members || []).map(m => m.member_conv_id)]);
  useEffect(() => {
    let alive = true;
    async function refresh() {
      // A chat the cached list doesn't know yet (made since) is read once more.
      const found = await resolveOwner(ownerId);
      if (alive) setOwner(found);
    }
    void refresh();
    const unsubscribe = subscribeAgentEvents(event => {
      if (event.type === "chats_changed" || event.type === "plan_assignment_changed") {
        directory = undefined; void refresh();
      }
      const eventChat = event.type === "linked_agent" ? event.parent_conv_id || event.conv_id : event.conv_id;
      if (!eventChat || !tracked.current.has(eventChat)) return;
      if (event.type === "linked_agent" && event.child_conv_id) {
        const linked = waiting.current.get(eventChat) || new Set<string>();
        if (event.status === "running") linked.add(event.child_conv_id);
        else linked.delete(event.child_conv_id);
        waiting.current.set(eventChat, linked);
        setNow(Date.now());
      }
      if (event.type === "agent_stopped" || event.type === "error") waiting.current.delete(eventChat);
      const label = ownerActivity(event);
      if (event.conv_id && label !== undefined) setActivity(old => ({ ...old, [event.conv_id!]: label }));
    });
    return () => { alive = false; unsubscribe(); };
  }, [ownerId]);
  const assigned = nodeId ? members?.filter(member => member.observation?.assignment?.node_id === nodeId) : undefined;
  const shown = assigned?.length ? assigned : members || [];
  const chips: Owner[] = [owner, ...shown.map(member => ({ id: member.member_conv_id, name: member.name || member.ducky_name || member.member_conv_id, style: member.ducky_style }))];
  // Only a running chip shows a clock. A plan renders one of these per assigned step, and
  // each used to re-render every second whether anyone was working or not.
  const ticking = chips.some(chip => running.has(chip.id) && getChatTurnTimer(chip.id)?.startedAt);
  useEffect(() => {
    if (!ticking) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);
  return <div className="plan-owner-chips" aria-label="Plan owners">
    {chips.filter(chip => !activeOnly || running.has(chip.id)).map(chip => {
      const isRunning = running.has(chip.id);
      const cached = getCachedChatMessages(chip.id);
      const lines = cached ? buildActivityLines(splitTurnMessages(cached.messages, isRunning).turnMessages, cached.streamBuffer, cached.streamThinking) : [];
      const awaiting = waiting.current.get(chip.id)?.size || 0;
      const label = isRunning ? awaiting ? "Waiting for reply" : activity[chip.id] || activityPanelTitle(lines, false, 0, undefined, cached?.run?.statusText || "Working") : "Idle";
      const start = getChatTurnTimer(chip.id)?.startedAt;
      const seconds = start ? Math.max(0, Math.floor((now - start) / 1000)) : 0;
      const duration = isRunning && start ? ` ${Math.floor(seconds / 60)}m ${seconds % 60}s` : "";
      return <button key={chip.id} type="button" className="plan-owner-chip" data-running={isRunning} onClick={() => {
        requestLatestChatActivity(chip.id);
        requestOpenChatTab(chip.id, chip.name);
      }} title={`Open ${chip.name} at latest activity`}>
        <DuckyAvatar styleId={chip.style} size={20} />
        <span>{chip.name}</span><span className="plan-owner-activity">{label}{duration}</span>
      </button>;
    })}
  </div>;
}

// A plan tab highlights the node it was opened for: delivered at once to a pane already
// showing that chat's plan, otherwise kept until the pane's first load takes it.
const pendingHighlight = new Map<string, string>();
const highlightListeners = new Map<string, Set<(nodeId: string) => void>>();

export function requestPlanHighlight(chatId: string, nodeId: string): void {
  const live = highlightListeners.get(chatId);
  if (live?.size) live.forEach(fn => fn(nodeId));
  else pendingHighlight.set(chatId, nodeId);
}

export function takePlanHighlight(chatId: string): string | null {
  const nodeId = pendingHighlight.get(chatId) ?? null;
  pendingHighlight.delete(chatId);
  return nodeId;
}

export function onPlanHighlight(chatId: string, fn: (nodeId: string) => void): () => void {
  const set = highlightListeners.get(chatId) ?? new Set();
  set.add(fn);
  highlightListeners.set(chatId, set);
  return () => { set.delete(fn); };
}

export function openLeadPlan(chatId: string, title: string, nodeId: string): void {
  requestPlanHighlight(chatId, nodeId);
  requestOpenPlanTab({ chatId, title });
}

/** Lead and Full plan buttons for a member's part of a team plan, with the parent sections as a crumb. */
export function PlanLeadLinks({ assignedFrom }: { assignedFrom: NonNullable<ChatPlan["assigned_from"]> }) {
  const { chat_id: leadId, node_id: nodeId, plan_title: title } = assignedFrom;
  const [leadName, setLeadName] = useState(leadId);
  const [sections, setSections] = useState<PlanNode[]>([]);
  useEffect(() => {
    let alive = true;
    void owners().then(rows => {
      const row = rows.find(r => r.id === leadId);
      if (alive && row) setLeadName(row.name);
    });
    // ponytail: reads the lead's whole plan once per mount for the crumb; a path-only call if big plans make this slow.
    void getApi()?.get_plan?.(leadId, null).then(res => {
      if (alive) setSections(findNodePath(res.plan?.nodes, nodeId) || []);
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [leadId, nodeId]);
  return <nav className="plan-pane-nest-crumb plan-lead-links" aria-label="Lead plan">
    <button type="button" className="plan-pane-btn plan-pane-btn--ghost" onClick={() => requestOpenChatTab(leadId, leadName)}
      title="Open the lead's chat">Lead: {leadName}</button>
    <span className="plan-pane-nest-crumb-sep" aria-hidden>·</span>
    <button type="button" className="plan-pane-btn plan-pane-btn--accent" onClick={() => openLeadPlan(leadId, title, nodeId)}
      title="This chat's part of a team plan. Open the whole plan to edit it.">Full plan</button>
    {sections.map(node => <span key={node.id}>
      <span className="plan-pane-nest-crumb-sep" aria-hidden>›</span>
      <button type="button" className="plan-pane-nest-crumb-link" onClick={() => openLeadPlan(leadId, title, node.id)}>{node.content}</button>
    </span>)}
  </nav>;
}
