import { useEffect, useMemo, useState } from "react";
import { subscribeAgentEvents } from "../../hooks/useAgentEventBus";
import { getApi } from "../../hooks/usePanelApi";
import type { AgentEvent, GroupMemberDto, PanelApi } from "../../types/panel";

/**
 * One cached roster per group. Every view (team bar, nested rosters, sidebar progress)
 * reads the same entry: the first reader fetches `group_members`, the rest share it, and
 * pushes refresh only the group they name. Nothing polls.
 */
export type Roster = { members: GroupMemberDto[]; leaderConvId: string };

type MembersApi = Partial<Pick<PanelApi, "group_members">>;

type Entry = {
  roster: Roster | null;
  pending: Promise<Roster> | null;
  /** Bumped per fetch: a late answer for an older fetch is dropped. */
  seq: number;
  timer: ReturnType<typeof setTimeout> | null;
  subs: Set<() => void>;
};

/** A roster change (member added/removed, leader set) pushes chats_changed with the group id. */
const ROSTER_MS = 1000;
/** A member started, stopped or got a new step: its row's observation, at most every 5 s. */
const ACTIVITY_MS = 5000;
const ROSTER_PUSHES = new Set(["chats_changed", "group_member_added", "group_member_removed", "group_leader_set"]);
const ACTIVITY_PUSHES = new Set(["plan_updated", "plan_assignment_changed", "agent_started", "agent_stopped"]);
const EMPTY: Roster = { members: [], leaderConvId: "" };

const entries = new Map<string, Entry>();
let unsubscribe: (() => void) | null = null;

function entry(groupId: string): Entry {
  let e = entries.get(groupId);
  if (!e) {
    e = { roster: null, pending: null, seq: 0, timer: null, subs: new Set() };
    entries.set(groupId, e);
  }
  return e;
}

function notify(e: Entry): void {
  for (const fn of [...e.subs]) fn();
}

function fetchRoster(groupId: string, api: MembersApi | null | undefined = getApi()): Promise<Roster> {
  const e = entry(groupId);
  const seq = ++e.seq;
  const call = api?.group_members?.(groupId) ?? Promise.resolve(null);
  const pending = Promise.resolve(call)
    .then((res) => (res?.ok ? { members: res.members || [], leaderConvId: res.leader_conv_id || "" } : EMPTY))
    .catch(() => EMPTY)
    .then((roster) => {
      if (seq === e.seq) {
        e.roster = roster;
        e.pending = null;
        notify(e);
      }
      return e.roster ?? roster;
    });
  e.pending = pending;
  return pending;
}

/** The cached roster, fetched once; concurrent callers share one call. */
export function loadRoster(groupId: string, api?: MembersApi | null): Promise<Roster> {
  ensureSubscribed();
  const e = entry(groupId);
  if (e.roster) return Promise.resolve(e.roster);
  if (e.pending) return e.pending;
  return fetchRoster(groupId, api ?? getApi());
}

/** What the store holds now (no fetch). */
export function peekRoster(groupId: string): Roster | null {
  return entries.get(groupId)?.roster ?? null;
}

/** A mutation's reply already carries the new roster: store it, no fetch. */
export function setRoster(groupId: string, members: GroupMemberDto[], leaderConvId?: string): void {
  const e = entry(groupId);
  e.seq += 1;
  e.pending = null;
  e.roster = { members, leaderConvId: leaderConvId ?? e.roster?.leaderConvId ?? "" };
  notify(e);
}

/** Read again now (the Refresh button). */
export function refreshRoster(groupId: string): Promise<Roster> {
  const e = entry(groupId);
  if (e.timer !== null) clearTimeout(e.timer);
  e.timer = null;
  return fetchRoster(groupId);
}

/** Read again after `delay`; more pushes inside the window ride along. Unwatched groups are only dropped. */
function refreshSoon(groupId: string, delay: number): void {
  const e = entries.get(groupId);
  if (!e) return;
  if (e.subs.size === 0) {
    if (e.timer !== null) clearTimeout(e.timer);
    entries.delete(groupId);
    return;
  }
  if (e.timer !== null) return;
  e.timer = setTimeout(() => {
    e.timer = null;
    if (e.subs.size > 0) void fetchRoster(groupId);
  }, delay);
}

/** Groups a chat id belongs to: the group itself, a member, or the owner of a member's assignment. */
function groupsFor(convId: string): string[] {
  const out: string[] = [];
  for (const [groupId, e] of entries) {
    if (groupId === convId) out.push(groupId);
    else if (e.roster?.members.some((m) => m.member_conv_id === convId || m.observation?.assignment?.chat_id === convId)) {
      out.push(groupId);
    }
  }
  return out;
}

function onPush(event: AgentEvent): void {
  const type = event.type as string;
  const convId = String((event as { group_id?: string }).group_id || event.conv_id || "");
  if (ROSTER_PUSHES.has(type)) {
    // No id (archive, delete): any roster may have lost a member.
    const ids = convId ? (entries.has(convId) ? [convId] : []) : [...entries.keys()];
    const removed = (event as { removed_conv_ids?: string[] }).removed_conv_ids || [];
    for (const gone of removed) for (const id of groupsFor(gone)) if (!ids.includes(id)) ids.push(id);
    for (const id of ids) refreshSoon(id, ROSTER_MS);
    return;
  }
  if (!ACTIVITY_PUSHES.has(type) || !convId) return;
  for (const id of groupsFor(convId)) {
    const e = entries.get(id)!;
    // A sidebar row only reads assignments; runtime changes matter to a watched team bar.
    if (e.subs.size > 0) refreshSoon(id, ACTIVITY_MS);
    else if (type === "plan_assignment_changed") refreshSoon(id, ACTIVITY_MS);
  }
}

function ensureSubscribed(): void {
  if (!unsubscribe) unsubscribe = subscribeAgentEvents(onPush);
}

/** Watch a group: fetch once if not cached, re-render on changes. */
export function subscribeRoster(groupId: string, fn: () => void): () => void {
  ensureSubscribed();
  const e = entry(groupId);
  e.subs.add(fn);
  if (!e.roster && !e.pending) void fetchRoster(groupId);
  return () => {
    e.subs.delete(fn);
  };
}

/** One group's roster; `null` until the first answer. */
export function useRoster(groupId: string): Roster | null {
  const [, bump] = useState(0);
  useEffect(() => {
    if (!groupId) return;
    return subscribeRoster(groupId, () => bump((n) => n + 1));
  }, [groupId]);
  return groupId ? peekRoster(groupId) : null;
}

/** Several groups' members by id (nested groups of a team); a group not loaded yet is left out. */
export function useRosters(groupIds: readonly string[]): Record<string, GroupMemberDto[]> {
  const key = [...new Set(groupIds.filter(Boolean))].sort().join("|");
  const [version, bump] = useState(0);
  useEffect(() => {
    if (!key) return;
    const tick = () => bump((n) => n + 1);
    const offs = key.split("|").map((id) => subscribeRoster(id, tick));
    return () => { for (const off of offs) off(); };
  }, [key]);
  return useMemo(() => {
    const out: Record<string, GroupMemberDto[]> = {};
    for (const id of key ? key.split("|") : []) {
      const roster = peekRoster(id);
      if (roster) out[id] = roster.members;
    }
    return out;
  }, [key, version]); // version: re-read the store after a change
}

/** Tests only: forget every cached roster and the push subscription. */
export function resetRosterStore(): void {
  for (const e of entries.values()) if (e.timer !== null) clearTimeout(e.timer);
  entries.clear();
  unsubscribe?.();
  unsubscribe = null;
}
