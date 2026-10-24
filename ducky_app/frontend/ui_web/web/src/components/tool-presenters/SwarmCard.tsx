import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { RichChart } from "../rich-content/RichChart";
import type { ChartSpec, TreeNode } from "../rich-content/RichChart";

// ducky_swarm_create results drawn as a tree: needs_confirm is the preview
// (Build / Change), building reveals each node as it is created, done shows
// rolled-up progress. The drawing is RichChart's tree; this card only tags
// its nodes (placement order mirrors TreeChart's post-order walk).

export const SWARM_REVEAL_MS = 120;
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const STATUSES = new Set(["needs_confirm", "building", "done"]);

export interface SwarmProgress {
  done: number;
  total: number;
}

export interface SwarmSeat {
  kind: "seat";
  key: string;
  name: string;
  profile: string;
  model: string;
  created: boolean;
  plan: string;
  progress?: SwarmProgress;
}

export interface SwarmGroup {
  kind: "group";
  key: string;
  name: string;
  purpose: string;
  muted: boolean;
  created: boolean;
  plan: string;
  progress?: SwarmProgress;
  seats: SwarmSeat[];
  groups: SwarmGroup[];
}

export interface SwarmLevel {
  detail: number;
  label: string;
  agents: number;
}

export interface SwarmCardData {
  status: string;
  goal: string;
  agents: number;
  groups: SwarmGroup[];
  seats: SwarmSeat[];
  detail?: number;
  levels: SwarmLevel[];
}

export const SWARM_DETAIL_LABELS = ["Areas", "Jobs", "Parts", "Parts in sub-groups"];

/** preview.levels as a list or keyed by level; each needs an agent count. */
function parseLevels(v: unknown): SwarmLevel[] {
  const rows = Array.isArray(v) ? v : Object.entries(obj(v) ?? {}).map(([k, x]) => ({ detail: Number(k), ...(obj(x) ?? { agents: x }) }));
  return rows.flatMap((r, i) => {
    const o: Raw = obj(r) ?? { agents: r };
    const detail = num(o.detail) ?? num(o.level) ?? i + 1;
    const agents = num(o.agents);
    if (agents === undefined || detail < 1 || detail > SWARM_DETAIL_LABELS.length) return [];
    return [{ detail, label: str(o.label) || SWARM_DETAIL_LABELS[detail - 1], agents }];
  });
}

type Raw = Record<string, unknown>;

const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const obj = (v: unknown): Raw | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function progressOf(raw: Raw): SwarmProgress | undefined {
  for (const v of [raw.progress, raw.sub_plan, raw.subPlan, raw]) {
    const o = obj(v);
    if (o) {
      const total = num(o.total);
      if (total !== undefined) return { done: num(o.done) ?? num(o.completed) ?? 0, total };
    } else if (typeof v === "string") {
      const m = /(\d+)\s*\/\s*(\d+)/.exec(v);
      if (m) return { done: Number(m[1]), total: Number(m[2]) };
    }
  }
  return undefined;
}

function planName(raw: Raw): string {
  const sp = raw.sub_plan ?? raw.subPlan;
  if (typeof sp === "string") return sp.replace(/\s*\d+\s*\/\s*\d+\s*$/, "").trim();
  const o = obj(sp);
  return o ? str(o.title) || str(o.content) || str(o.id) : "";
}

function wasCreated(raw: Raw, allDone: boolean): boolean {
  if (allDone || raw.created === true) return true;
  if (raw.created === false) return false;
  return Boolean(str(raw.id) || str(raw.group_id) || str(raw.conv_id) || str(raw.chat_id));
}

function toSeat(v: unknown, key: string, allDone: boolean): SwarmSeat | null {
  if (typeof v === "string") {
    return v.trim() ? { kind: "seat", key, name: v.trim(), profile: "", model: "", created: allDone, plan: "" } : null;
  }
  const raw = obj(v);
  if (!raw) return null;
  const name = str(raw.name) || str(raw.seat) || str(raw.role);
  if (!name) return null;
  return {
    kind: "seat",
    key,
    name,
    profile: str(raw.profile) || str(raw.template) || str(raw.profile_id),
    model: str(raw.model),
    created: wasCreated(raw, allDone),
    plan: planName(raw),
    progress: progressOf(raw),
  };
}

function isGroup(raw: Raw): boolean {
  return typeof raw.group === "string" || Array.isArray(raw.seats) || Array.isArray(raw.groups);
}

function toGroup(raw: Raw, key: string, allDone: boolean): SwarmGroup {
  const seats: SwarmSeat[] = [];
  const groups: SwarmGroup[] = [];
  arr(raw.seats).forEach((s, i) => {
    const seat = toSeat(s, `${key}/s${i}`, allDone);
    if (seat) seats.push(seat);
  });
  arr(raw.groups ?? raw.children).forEach((g, i) => {
    const o = obj(g);
    if (!o) return;
    if (isGroup(o)) groups.push(toGroup(o, `${key}/g${i}`, allDone));
    else {
      const seat = toSeat(o, `${key}/c${i}`, allDone);
      if (seat) seats.push(seat);
    }
  });
  return {
    kind: "group",
    key,
    name: str(raw.group) || str(raw.name) || "Group",
    purpose: str(raw.purpose),
    muted: raw.muted === true,
    created: wasCreated(raw, allDone),
    plan: planName(raw),
    progress: progressOf(raw),
    seats,
    groups,
  };
}

export function countSeats(g: { seats: SwarmSeat[]; groups: SwarmGroup[] }): number {
  return g.seats.length + g.groups.reduce((n, sub) => n + countSeats(sub), 0);
}

function countGroups(groups: SwarmGroup[]): number {
  return groups.reduce((n, g) => n + 1 + countGroups(g.groups), 0);
}

function allSeats(g: { seats: SwarmSeat[]; groups: SwarmGroup[] }): SwarmSeat[] {
  return [...g.seats, ...g.groups.flatMap(allSeats)];
}

/** A ducky_swarm_create result (raw tool text) → card data; null for other statuses. */
export function parseSwarmResult(text: string): SwarmCardData | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text.trim());
  } catch {
    return null;
  }
  let top = obj(parsed);
  if (top && obj(top.data) && !str(top.status)) top = obj(top.data);
  if (!top) return null;
  const status = str(top.status);
  if (!STATUSES.has(status)) return null;
  const preview = obj(top.preview);
  const tree = status === "needs_confirm" ? (preview?.tree ?? top.tree) : (top.tree ?? preview?.tree);
  const allDone = status === "done";
  const groups: SwarmGroup[] = [];
  const seats: SwarmSeat[] = [];
  arr(tree).forEach((entry, i) => {
    if (typeof entry === "string") {
      const seat = toSeat(entry, `s${i}`, allDone);
      if (seat) seats.push(seat);
      return;
    }
    const raw = obj(entry);
    if (!raw) return;
    if (isGroup(raw)) groups.push(toGroup(raw, `g${i}`, allDone));
    else {
      const seat = toSeat(raw, `s${i}`, allDone);
      if (seat) seats.push(seat);
    }
  });
  const goal = str(top.goal) || str(preview?.goal) || str(top.name);
  const agents = num(preview?.agents) ?? num(top.agents) ?? countSeats({ seats, groups });
  const detail = num(preview?.detail) ?? num(top.detail);
  return { status, goal, agents, groups, seats, detail, levels: parseLevels(preview?.levels ?? top.levels) };
}

/** Done/total over every sub plan under a node; a sub plan shared by two rows counts once. */
export function swarmRollup(node: { seats: SwarmSeat[]; groups: SwarmGroup[]; key?: string; plan?: string; progress?: SwarmProgress }): SwarmProgress & { pct: number } {
  const seen = new Map<string, SwarmProgress>();
  const add = (n: { key?: string; plan?: string; progress?: SwarmProgress }) => {
    if (n.progress) seen.set(n.plan || n.key || String(seen.size), n.progress);
  };
  const walk = (g: { seats: SwarmSeat[]; groups: SwarmGroup[]; key?: string; plan?: string; progress?: SwarmProgress }) => {
    add(g);
    g.seats.forEach(add);
    g.groups.forEach(walk);
  };
  walk(node);
  let done = 0;
  let total = 0;
  seen.forEach((p) => {
    done += p.done;
    total += p.total;
  });
  return { done, total, pct: total ? Math.round((done / total) * 100) : 0 };
}

type DrawNode = { key: string; label: string; color: string; children: DrawNode[] };

function seatLabel(s: SwarmSeat, live: boolean): string {
  if (live && s.progress) return `${s.name} · ${s.progress.done}/${s.progress.total}`;
  return [s.name, s.profile, s.model].filter(Boolean).join(" · ");
}

function groupNode(g: SwarmGroup, live: boolean): DrawNode {
  const n = countSeats(g);
  const roll = swarmRollup(g);
  const head = live && roll.total ? `${g.name} · ${roll.pct}%` : `${g.name} · ${n} agent${n === 1 ? "" : "s"}`;
  if (g.muted) return { key: g.key, label: `${head} · MUTED`, color: "amber", children: [] };
  return {
    key: g.key,
    label: head,
    color: "purple",
    children: [
      ...g.groups.map((sub) => groupNode(sub, live)),
      ...g.seats.map((s) => ({ key: s.key, label: seatLabel(s, live), color: "green", children: [] })),
    ],
  };
}

function drawTree(data: SwarmCardData): DrawNode {
  const live = data.status !== "needs_confirm";
  const roll = swarmRollup(data);
  const rootLabel = live ? (roll.total ? `Lead · ${roll.pct}%` : "Lead") : data.goal ? `Lead · ${data.goal}` : "Lead";
  return {
    key: "root",
    label: rootLabel,
    color: "blue",
    children: [
      ...data.groups.map((g) => groupNode(g, live)),
      ...data.seats.map((s) => ({ key: s.key, label: seatLabel(s, live), color: "green", children: [] })),
    ],
  };
}

function toTreeNode(n: DrawNode): TreeNode {
  return n.children.length ? { label: n.label, color: n.color, children: n.children.map(toTreeNode) } : { label: n.label, color: n.color };
}

/** Keys in TreeChart's order: nodes post-order, edges by child in the order TreeChart draws them. */
function chartOrder(root: DrawNode): { nodes: string[]; edges: string[] } {
  const nodes: string[] = [];
  const edges: string[] = [];
  const place = (n: DrawNode): void => {
    n.children.forEach(place);
    nodes.push(n.key);
    n.children.forEach((c) => edges.push(c.key));
  };
  place(root);
  return { nodes, edges };
}

/** Drawn nodes in creation order (a group before its seats), root excluded. */
function revealOrder(root: DrawNode): string[] {
  const out: string[] = [];
  const walk = (n: DrawNode) => {
    n.children.forEach((c) => {
      out.push(c.key);
      walk(c);
    });
  };
  walk(root);
  return out;
}

function createdKeys(data: SwarmCardData): Set<string> {
  const keys = new Set<string>();
  const walk = (g: SwarmGroup) => {
    if (g.created) keys.add(g.key);
    g.seats.forEach((s) => s.created && keys.add(s.key));
    g.groups.forEach(walk);
  };
  data.groups.forEach(walk);
  data.seats.forEach((s) => s.created && keys.add(s.key));
  return keys;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(REDUCED_MOTION).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(REDUCED_MOTION);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

export const SWARM_BUILD_PROMPT =
  "Build the swarm exactly as previewed: call ducky_swarm_create again with the same arguments and confirm=true.";
export const SWARM_CHANGE_PROMPT =
  "Change the swarm preview: ask me with one ducky_ask_user what to change (rename or drop a job, a seat's model, mute or unmute a group), then call ducky_swarm_create with those edits and show the new preview.";

export const SWARM_DETAIL_DEBOUNCE_MS = 400;

export function swarmDetailPrompt(detail: number): string {
  return `Show the swarm preview at detail level ${detail} (${SWARM_DETAIL_LABELS[detail - 1]}): call ducky_swarm_create again with the same arguments and detail=${detail}, without confirm.`;
}

export function swarmBuildPrompt(detail?: number): string {
  return detail === undefined
    ? SWARM_BUILD_PROMPT
    : `Build the swarm exactly as previewed: call ducky_swarm_create again with the same arguments, detail=${detail} and confirm=true.`;
}

type SwarmAction = "build" | "change" | "detail";

/** Bubbles from the card to the chat pane that shows it; that pane alone sends the text. */
export const SWARM_CARD_EVENT = "ducky:swarm-card";

/** The chat pane side: send a card's text through this pane's own send path. */
export function useSwarmCardSend(host: HTMLElement | null, send: (text: string) => void): void {
  const sendRef = useRef(send);
  sendRef.current = send;
  useEffect(() => {
    if (!host) return;
    const onCard = (e: Event) => {
      const text = (e as CustomEvent<{ text?: unknown }>).detail?.text;
      if (typeof text !== "string" || !text.trim()) return;
      e.stopPropagation();
      sendRef.current(text);
    };
    host.addEventListener(SWARM_CARD_EVENT, onCard);
    return () => host.removeEventListener(SWARM_CARD_EVENT, onCard);
  }, [host]);
}

export interface SwarmCardProps {
  resultText?: string;
  data?: SwarmCardData | null;
  onSend?: (action: SwarmAction, text: string) => void;
}

export function SwarmCard({ resultText = "", data: dataProp, onSend: onSendProp }: SwarmCardProps) {
  const cardRef = useRef<HTMLElement>(null);
  const onSend = (action: SwarmAction, text: string) => {
    if (onSendProp) onSendProp(action, text);
    else cardRef.current?.dispatchEvent(new CustomEvent(SWARM_CARD_EVENT, { detail: { action, text }, bubbles: true }));
  };
  const data = useMemo(() => dataProp ?? parseSwarmResult(resultText), [dataProp, resultText]);
  const reduced = usePrefersReducedMotion();
  const tree = useMemo(() => (data ? drawTree(data) : null), [data]);
  const order = useMemo(() => (tree ? revealOrder(tree) : []), [tree]);
  const placement = useMemo(() => (tree ? chartOrder(tree) : { nodes: [], edges: [] }), [tree]);
  const created = useMemo(() => (data ? createdKeys(data) : new Set<string>()), [data]);
  const status = data?.status ?? "";

  // A card first seen while building animates; a finished one (history) shows at once.
  const animates = useRef(status === "building");
  if (status === "building") animates.current = true;
  const [revealed, setRevealed] = useState<string[]>(() => (status === "building" ? [] : order));

  const due = useMemo(() => order.filter((k) => created.has(k)), [order, created]);
  const shown = reduced || !animates.current ? (status === "needs_confirm" ? order : due) : revealed;
  const nextKey = due.find((k) => !revealed.includes(k));

  useEffect(() => {
    if (reduced || !animates.current || !nextKey) return;
    const timer = window.setTimeout(() => setRevealed((r) => (r.includes(nextKey) ? r : [...r, nextKey])), SWARM_REVEAL_MS);
    return () => window.clearTimeout(timer);
  }, [nextKey, reduced]);

  // Dragging across stops sends only where it settles.
  const [picked, setPicked] = useState<number | undefined>();
  const sendTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(sendTimer.current), []);
  const pickDetail = (n: number) => {
    setPicked(n);
    window.clearTimeout(sendTimer.current);
    sendTimer.current = window.setTimeout(() => onSend("detail", swarmDetailPrompt(n)), SWARM_DETAIL_DEBOUNCE_MS);
  };

  const hostRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const building = status !== "needs_confirm";
    const animate = animates.current && !reduced;
    const tag = (el: Element, key: string, base: string) => {
      const step = shown.indexOf(key);
      el.setAttribute("data-swarm-key", key);
      el.classList.add(base);
      el.classList.toggle(`${base}--created`, building && (key === "root" || step >= 0));
      el.classList.toggle(`${base}--pending`, building && key !== "root" && step < 0);
      el.classList.toggle(`${base}--animate`, animate && step >= 0);
      if (step >= 0) el.setAttribute("data-swarm-step", String(step));
      else el.removeAttribute("data-swarm-step");
    };
    const marks = host.querySelectorAll("g.rich-chart-mark");
    placement.nodes.forEach((key, i) => marks[i] && tag(marks[i], key, "swarm-node"));
    const edges = host.querySelectorAll("path.rich-chart-edge");
    placement.edges.forEach((key, i) => edges[i] && tag(edges[i], key, "swarm-edge"));
  });

  if (!data || !tree) return null;

  const groupCount = countGroups(data.groups) + 1;
  const roll = swarmRollup(data);
  const models = new Map<string, number>();
  allSeats(data).forEach((s) => s.model && models.set(s.model, (models.get(s.model) ?? 0) + 1));
  const modelText = [...models].map(([m, n]) => (n > 1 ? `${m} ×${n}` : m)).join(", ");
  const goal = data.goal || "swarm";
  const title =
    status === "needs_confirm"
      ? `Swarm preview: ${goal} · ${data.agents} agents · ${groupCount} groups`
      : status === "building"
        ? `Building swarm: ${goal}`
        : `Swarm built: ${goal}`;
  const builtSeats = allSeats(data).filter((s) => s.created).length;
  const summary =
    status === "needs_confirm"
      ? [`${data.agents} agents`, `${groupCount} groups`, modelText && `models: ${modelText}`].filter(Boolean).join(" · ")
      : status === "building"
        ? `Building ${builtSeats}/${data.agents} agents…`
        : `Built ${data.agents} agents · ${roll.done}/${roll.total} steps`;
  const spec: ChartSpec = { type: "tree", title: "", root: toTreeNode(tree) };
  const levels = status === "needs_confirm" ? data.levels : [];
  const detail = picked ?? data.detail ?? levels[0]?.detail;

  return (
    <section ref={cardRef} className={`swarm-card swarm-card--${status.replace("_", "-")}`} aria-label={title}>
      <header className="swarm-card-title">{title}</header>
      {levels.length ? (
        <div className="swarm-card-detail">
          <input
            type="range"
            className="swarm-card-detail-range"
            aria-label="Detail"
            min={1}
            max={SWARM_DETAIL_LABELS.length}
            step={1}
            value={detail ?? 1}
            aria-valuetext={SWARM_DETAIL_LABELS[(detail ?? 1) - 1]}
            onChange={(e) => pickDetail(Number(e.currentTarget.value))}
          />
          <div className="swarm-card-detail-stops">
            {SWARM_DETAIL_LABELS.map((label, i) => {
              const level = levels.find((l) => l.detail === i + 1);
              return (
                <span key={label} className={`swarm-card-detail-stop${detail === i + 1 ? " swarm-card-detail-stop--on" : ""}`}>
                  {level ? `${level.label} · ${level.agents} agents` : label}
                </span>
              );
            })}
          </div>
        </div>
      ) : null}
      <div ref={hostRef} className="swarm-card-tree">
        <RichChart spec={spec} />
      </div>
      <div className="swarm-card-summary">{summary}</div>
      {status === "needs_confirm" ? (
        <div className="swarm-card-actions">
          <button type="button" className="swarm-card-btn swarm-card-btn--primary" onClick={() => onSend("build", swarmBuildPrompt(levels.length ? detail : undefined))}>
            Build
          </button>
          <button type="button" className="swarm-card-btn" onClick={() => onSend("change", SWARM_CHANGE_PROMPT)}>
            Change
          </button>
        </div>
      ) : null}
    </section>
  );
}
