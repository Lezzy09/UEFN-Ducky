import type { AgentProfileDto, ChatTab, FolderItem, GroupMemberDto } from "../../types/panel";
import { modelFromFavorites } from "../ducky/duckyProfileForm";
import { resolveNestedGroupHoverRows, shortModelLabel } from "../groupMemberHover";

/** One row of a group chat's team: an agent, or a nested group with its own rows. */
export type RosterNode = {
  /** Unique in the tree: the group it sits in + its chat id. */
  key: string;
  /** The group this row belongs to; model, lane and remove go to that group. */
  hubId: string;
  /** Null for a read-only row (a nested group's agents read from the sidebar tree). */
  member: GroupMemberDto | null;
  id: string;
  name: string;
  styleId?: string;
  model: string;
  codingAgent: string;
  /** API provider of an embedded (ducky) member: decides how its turns are billed. */
  provider?: string;
  contextTokens: number;
  isGroup: boolean;
  isLeader: boolean;
  color?: string;
  /** Short "when to use" from the ducky's profile. */
  blurb: string;
  depth: number;
  children: RosterNode[];
};

export type RosterInput = {
  groupId: string;
  members: GroupMemberDto[];
  leaderConvId: string;
  /** Nested group id → its members, as the bridge returned them. */
  rosters: Record<string, GroupMemberDto[]>;
  folders: FolderItem[];
  allChats: ChatTab[];
  profileById: Map<string, AgentProfileDto>;
  labelFor: (styleId?: string | null) => string;
};

/** Library profile title (Verse Coder), then the role, then the duck name; never the avatar style. */
export function memberDisplayName(
  m: GroupMemberDto,
  profile: AgentProfileDto | undefined,
  labelFor: (styleId?: string | null) => string,
): string {
  if (m.is_group) return (m.name || m.ducky_name || "Group").trim() || "Group";
  return (
    (profile?.name || "").trim() ||
    (m.name || "").trim() ||
    (m.ducky_name || "").trim() ||
    labelFor(m.ducky_style || profile?.ducky_style)
  );
}

const MAX_DEPTH = 4;

/** The whole team as a tree: direct members first, nested groups with their own agents. */
export function buildRoster(input: RosterInput): RosterNode[] {
  const chatById = new Map(input.allChats.map((c) => [c.id, c]));
  const seen = new Set<string>([input.groupId]);

  const nodeFor = (m: GroupMemberDto, hubId: string, leaderId: string, depth: number): RosterNode => {
    const chat = chatById.get(m.member_conv_id);
    const profile = input.profileById.get(m.profile_id);
    const isGroup = Boolean(m.is_group);
    const node: RosterNode = {
      key: `${hubId}/${m.member_conv_id}`,
      hubId,
      member: m,
      id: m.member_conv_id,
      name: memberDisplayName(m, profile, input.labelFor),
      styleId: m.ducky_style || profile?.ducky_style || chat?.duckyStyle,
      model: (m.model || "").trim() || (chat?.model || "").trim() || modelFromFavorites(profile?.favorite_models),
      codingAgent: (m.coding_agent || "").trim() || (chat?.codingAgent || "").trim() || "ducky",
      provider: (chat?.provider || "").trim(),
      contextTokens: Math.max(0, Number(chat?.contextTokens) || 0),
      isGroup,
      isLeader: !isGroup && Boolean(leaderId) && m.member_conv_id === leaderId,
      color: m.color,
      blurb: isGroup ? "" : (profile?.when_to_use || profile?.ducky_personality || chat?.duckyPersonality || "").trim(),
      depth,
      children: [],
    };
    if (isGroup && depth < MAX_DEPTH && !seen.has(node.id)) {
      seen.add(node.id);
      node.children = childrenOf(node.id, depth + 1);
    }
    return node;
  };

  const childrenOf = (hubId: string, depth: number): RosterNode[] => {
    const fromBridge = input.rosters[hubId];
    if (fromBridge && fromBridge.length > 0) {
      const leader = (chatById.get(hubId)?.leaderConvId || "").trim();
      return fromBridge.map((m) => nodeFor(m, hubId, leader, depth));
    }
    // No roster from the bridge yet: show what the sidebar tree knows, read-only.
    return resolveNestedGroupHoverRows(hubId, input.folders, input.allChats, [], input.profileById, input.labelFor).map(
      (row) => ({
        key: `${hubId}/${row.id}`,
        hubId,
        member: null,
        id: row.id,
        name: row.name,
        styleId: row.duckyStyle,
        model: row.model,
        codingAgent: row.codingAgent,
        contextTokens: row.contextTokens,
        isGroup: row.isGroup,
        isLeader: false,
        blurb: "",
        depth,
        children: [],
      }),
    );
  };

  return input.members.map((m) => nodeFor(m, input.groupId, input.leaderConvId, 0));
}

/** Every agent (not group) in the tree, in display order. */
export function rosterAgents(nodes: RosterNode[]): RosterNode[] {
  const out: RosterNode[] = [];
  const walk = (list: RosterNode[]) => {
    for (const n of list) {
      if (n.isGroup) walk(n.children);
      else out.push(n);
    }
  };
  walk(nodes);
  return out;
}

/** Context of a row: its own, or the sum of every agent inside a group. */
export function rosterTokens(node: RosterNode): number {
  if (!node.isGroup) return node.contextTokens;
  return rosterAgents(node.children).reduce((sum, a) => sum + a.contextTokens, 0);
}

/** Rows matching the filter (name, model or coding agent); a group stays when any row inside matches. */
export function filterRoster(nodes: RosterNode[], query: string): RosterNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return nodes;
  const hit = (n: RosterNode) =>
    n.name.toLowerCase().includes(q) ||
    shortModelLabel(n.model).toLowerCase().includes(q) ||
    n.codingAgent.toLowerCase().replace(/_/g, " ").includes(q);
  const out: RosterNode[] = [];
  for (const n of nodes) {
    if (n.isGroup) {
      const children = hit(n) ? n.children : filterRoster(n.children, q);
      if (hit(n) || children.length > 0) out.push({ ...n, children });
    } else if (hit(n)) {
      out.push(n);
    }
  }
  return out;
}

/** Nested group ids anywhere in the tree (to fetch their rosters). */
export function rosterGroupIds(nodes: RosterNode[]): string[] {
  const out: string[] = [];
  const walk = (list: RosterNode[]) => {
    for (const n of list) {
      if (!n.isGroup) continue;
      out.push(n.id);
      walk(n.children);
    }
  };
  walk(nodes);
  return out;
}
