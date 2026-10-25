import { useEffect, useMemo, useRef, useState } from "react";
import { subscribeAgentEvents } from "../hooks/useAgentEventBus";
import { getApi } from "../hooks/usePanelApi";
import type { AgentEvent } from "../types/panel";
import { SWARM_CARD_EVENT, parseSwarmResult } from "../components/tool-presenters/SwarmCard";
import { GroupEditor, type SwarmGroup as EditorGroup } from "./GroupEditor";
import { laneOverlaps, overlapNotes } from "./lanes";
import { SeatEditor, type SwarmEdit, type SwarmSeat as EditorSeat } from "./SeatEditor";
import { SwarmTree } from "./SwarmTree";
import "./SwarmTree.css";

// The `ui: "swarm_builder"` payload (pinned in fixtures/swarm_builder.json) as a card:
// three sliders reshape the team through the pure swarm_preview panel method, Build sends
// confirm=true with those answers, then the same card follows each seat as it works.

export const SWARM_PREVIEW_DEBOUNCE_MS = 120;
const PLAN_EVENTS = new Set(["plan_updated", "plan_assignment_changed"]);
const PLAN_EVENT_COALESCE_MS = 300;
const WORK_EVENTS = new Set(["text_delta", "thinking", "tool", "tool_done"]);

export const DETAIL_NAMES = ["Areas", "Jobs", "Parts", "Parts in sub-groups"];
export const LIMITS = {
  detail: { min: 1, max: 4 },
  max_agents: { min: 1, max: 32 },
  per_group: { min: 2, max: 10 },
} as const;

type Raw = Record<string, unknown>;
const obj = (v: unknown): Raw | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const clamp = (n: number, lim: { min: number; max: number }) => Math.min(lim.max, Math.max(lim.min, Math.round(n)));

function parse(text: string): unknown {
  try {
    return JSON.parse(text.trim());
  } catch {
    return null;
  }
}

/** The swarm_builder payload in a value or JSON text ({result: json} and {data} wrappers too); else null. */
export function swarmBuilderPayload(v: unknown): Raw | null {
  let o = obj(typeof v === "string" ? parse(v) : v);
  if (o && typeof o.result === "string" && o.ui === undefined) o = obj(parse(o.result));
  if (o && o.ui === undefined && obj(o.data)) o = obj(o.data);
  return o && o.ui === "swarm_builder" && obj(o.preview) ? o : null;
}

export interface SwarmAnswers {
  detail: number;
  max_agents: number;
  per_group: number;
}

/** What Build sends: ducky_swarm_create's arguments for the tree on screen. */
export interface SwarmConfirm extends SwarmAnswers {
  goal: string;
  jobs: unknown[];
  agents: "auto";
  edits: SwarmEdit[];
  confirm: true;
}

export function answersOf(preview: Raw): SwarmAnswers {
  return {
    detail: clamp(num(preview.detail) ?? 2, LIMITS.detail),
    max_agents: clamp(num(preview.max_agents) ?? 8, LIMITS.max_agents),
    per_group: clamp(num(preview.per_group) ?? 5, LIMITS.per_group),
  };
}

export interface TreeRow {
  key: string;
  kind: "group" | "seat";
  name: string;
  label: string;
  muted: boolean;
  children: TreeRow[];
}

export function treeRows(tree: unknown, prefix = ""): TreeRow[] {
  return arr(tree).flatMap((entry, i): TreeRow[] => {
    const o = obj(entry);
    if (!o) return [];
    const key = `${prefix}${i}`;
    if (typeof o.group === "string" || Array.isArray(o.seats)) {
      const children = [...treeRows(o.groups, `${key}.g`), ...treeRows(o.seats, `${key}.s`)];
      return [{ key, kind: "group", name: str(o.group) || "Group", label: str(o.group) || "Group", muted: o.muted === true, children }];
    }
    const name = str(o.name);
    if (!name) return [];
    const steps = num(obj(o.sub_plan)?.total);
    const label = [name, str(o.profile), str(o.model), steps !== undefined ? `${steps} step${steps === 1 ? "" : "s"}` : ""]
      .filter(Boolean)
      .join(" · ");
    return [{ key, kind: "seat", name, label, muted: false, children: [] }];
  });
}

/** The preview tree as editor rows, with lane edits ({seat, paths}) applied in order. */
export function draftOf(tree: unknown, edits: SwarmEdit[]): { seats: EditorSeat[]; groups: EditorGroup[] } {
  const seats: EditorSeat[] = [];
  const groups: EditorGroup[] = [];
  const walk = (list: unknown) =>
    arr(list).forEach((entry) => {
      const o = obj(entry);
      if (!o) return;
      if (typeof o.group === "string" || Array.isArray(o.seats)) {
        groups.push({ group: str(o.group) || "Group", muted: o.muted === true });
        walk(o.groups);
        walk(o.seats);
        return;
      }
      const name = str(o.name);
      if (!name) return;
      const sp = obj(o.sub_plan);
      const steps = arr(sp?.steps).flatMap((x) => {
        const content = typeof x === "string" ? x.trim() : str(obj(x)?.content);
        return content ? [{ content, body_markdown: str(obj(x)?.body_markdown) || undefined }] : [];
      });
      seats.push({
        name,
        job: str(o.job) || name,
        model: str(o.model),
        paths: arr(o.paths).map(str).filter(Boolean),
        sub_plan: { title: str(sp?.title) || str(o.job) || name, steps },
      });
    });
  walk(tree);
  for (const e of edits) {
    const seat = seats.find((s) => s.name === e.seat);
    if (seat && Array.isArray(e.paths)) seat.paths = e.paths.map(String);
  }
  return { seats, groups };
}

function seatNames(rows: TreeRow[]): string[] {
  return rows.flatMap((r) => (r.kind === "seat" ? [r.name] : seatNames(r.children)));
}

/** "N agents · M groups" for the picked detail: that level's row, else the preview's own counts. */
export function countsLine(preview: Raw, detail: number): string {
  const level = arr(preview.levels).map(obj).find((l) => l && num(l.detail) === detail);
  const agents = num(level?.agents) ?? num(preview.agents) ?? seatNames(treeRows(preview.tree)).length;
  const groups = num(level?.groups) ?? treeRows(preview.tree).filter((r) => r.kind === "group").length;
  return `${agents} agent${agents === 1 ? "" : "s"} · ${groups} group${groups === 1 ? "" : "s"}`;
}

export type SeatState = "waiting" | "created" | "started" | "working" | "blocked" | "done";
const STATE_COLOR: Record<SeatState, string> = {
  waiting: "var(--muted)",
  created: "var(--blue)",
  started: "var(--blue)",
  working: "var(--purple)",
  blocked: "var(--amber)",
  done: "var(--green)",
};

/** One agent event on a seat's chat → the seat's next state (done comes from plan progress only). */
export function nextSeatState(prev: SeatState, event: Pick<AgentEvent, "type" | "text">): SeatState {
  if (prev === "done") return prev;
  if (event.type === "agent_started") return "started";
  if (WORK_EVENTS.has(event.type)) return "working";
  if ((event.type === "assistant_done" || event.type === "agent_stopped") && /\bBLOCKED:/.test(event.text ?? "")) return "blocked";
  return prev === "waiting" ? "created" : prev;
}

type PreviewApi = {
  swarm_preview?: (
    goal: string,
    jobs: unknown[],
    detail: number,
    agents: string,
    max_agents: number,
    per_group: number,
    edits: unknown[],
  ) => Promise<Raw | null | undefined>;
  plan_progress?: (chat_ids: string[]) => Promise<{ ok?: boolean; progress?: Record<string, { done?: number; total?: number; error?: string }> }>;
};

export interface SwarmBuilderCardProps {
  /** The swarm_builder payload (object or JSON text). */
  payload: unknown;
  /** The jobs the agent passed; swarm_preview reruns the preview from them. */
  jobs?: unknown;
  /** Seat name → its chat id, when already known (else learned from linked_agent events). */
  seatChats?: Record<string, string>;
  onBuild?: (confirm: SwarmConfirm) => void;
}

function Tree({ rows, states, progress }: { rows: TreeRow[]; states?: Record<string, SeatState>; progress?: Record<string, string> }) {
  return (
    <ul className="swarm-builder-tree" role="group">
      {rows.map((r) => {
        const state = r.kind === "seat" ? states?.[r.name] : undefined;
        return (
          <li key={r.key} role="treeitem" aria-selected={false} className={`swarm-builder-row swarm-builder-row--${r.kind}`} data-state={state}>
            {state ? <span className="swarm-builder-state" style={{ color: STATE_COLOR[state] }}>{state === "done" ? "✓ " : "● "}</span> : null}
            <span style={r.kind === "group" ? { color: r.muted ? "var(--amber)" : "var(--purple)" } : undefined}>
              {r.label}
              {r.muted ? " · MUTED" : ""}
            </span>
            {state ? <span className="swarm-builder-state-label"> · {state}{progress?.[r.name] ? ` ${progress[r.name]}` : ""}</span> : null}
            {r.children.length ? <Tree rows={r.children} states={states} progress={progress} /> : null}
          </li>
        );
      })}
    </ul>
  );
}

function Slider({ label, value, lim, text, onChange }: { label: string; value: number; lim: { min: number; max: number }; text: string; onChange: (n: number) => void }) {
  return (
    <label className="swarm-builder-slider">
      <span>
        {label}: {text}
      </span>
      <input
        type="range"
        aria-label={label}
        min={lim.min}
        max={lim.max}
        step={1}
        value={value}
        aria-valuetext={text}
        onChange={(e) => onChange(Number(e.currentTarget.value))}
      />
    </label>
  );
}

export function SwarmBuilderCard({ payload, jobs, seatChats, onBuild }: SwarmBuilderCardProps) {
  const initial = useMemo(() => swarmBuilderPayload(payload), [payload]);
  const [card, setCard] = useState<Raw | null>(initial);
  useEffect(() => setCard(initial), [initial]);
  const preview = obj(card?.preview) ?? {};
  const goal = str(card?.goal) || str(preview.goal);
  const jobList = arr(jobs);
  const [answers, setAnswers] = useState<SwarmAnswers>(() => answersOf(preview));
  const [error, setError] = useState("");
  const [built, setBuilt] = useState(false);
  const cardRef = useRef<HTMLElement>(null);

  // Slider moves and editor edits settle for 120 ms, then one swarm_preview; an older reply never wins.
  const [edits, setEdits] = useState<SwarmEdit[]>([]);
  const timer = useRef<number | undefined>(undefined);
  const asked = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const refresh = (next: SwarmAnswers, nextEdits: SwarmEdit[]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const call = (getApi() as unknown as PreviewApi | null)?.swarm_preview;
      if (!call || !goal || !jobList.length) return;
      const ticket = ++asked.current;
      void Promise.resolve(call(goal, jobList, next.detail, "auto", next.max_agents, next.per_group, nextEdits))
        .catch(() => null)
        .then((res) => {
          if (ticket !== asked.current || !res) return;
          if (res.ok === false) setError(str(res.error) || "The preview failed.");
          else if (swarmBuilderPayload(res)) {
            setError("");
            setCard(res);
          }
        });
    }, SWARM_PREVIEW_DEBOUNCE_MS);
  };
  const move = (patch: Partial<SwarmAnswers>) => {
    const next = { ...answers, ...patch };
    setAnswers(next);
    refresh(next, edits);
  };
  /** One editor change: kept in the card's edit list (Build sends them all) and previewed. */
  const edit = (e: SwarmEdit) => {
    const next = [...edits, e];
    setEdits(next);
    refresh(answers, next);
  };

  const rows = useMemo(() => treeRows(preview.tree), [preview.tree]);
  const names = useMemo(() => seatNames(rows), [rows]);
  // Lane edits apply at once, so the overlap check never waits on the preview round trip.
  const draft = useMemo(() => draftOf(preview.tree, edits), [preview.tree, edits]);
  const overlaps = useMemo(() => laneOverlaps(draft.seats), [draft]);
  const overlapSeats = useMemo(() => [...new Set(overlaps.flatMap((o) => [o.seat, o.other]))], [overlaps]);
  const treeData = useMemo(() => parseSwarmResult(JSON.stringify({ ...card, status: "needs_confirm" })), [card]);

  // After Build: one state per seat from its chat's events; done and counts from plan_progress.
  const [chats, setChats] = useState<Record<string, string>>(() => ({ ...seatChats }));
  useEffect(() => setChats((c) => ({ ...c, ...seatChats })), [seatChats]);
  const [states, setStates] = useState<Record<string, SeatState>>({});
  const [progress, setProgress] = useState<Record<string, string>>({});
  const chatKey = Object.entries(chats).map(([n, c]) => `${n}=${c}`).sort().join("|");
  useEffect(() => {
    if (!built) return;
    const seatOf = new Map(Object.entries(chats).map(([n, c]) => [c, n]));
    setStates((s) => {
      const out = { ...s };
      for (const n of names) if (!out[n] || (out[n] === "waiting" && chats[n])) out[n] = chats[n] ? "created" : "waiting";
      return out;
    });
    let live = true;
    const readProgress = async () => {
      const ids = [...seatOf.keys()];
      const call = (getApi() as unknown as PreviewApi | null)?.plan_progress;
      if (!call || !ids.length) return;
      const res = await Promise.resolve(call(ids)).catch(() => null);
      if (!live || !res?.ok) return;
      const counts: Record<string, string> = {};
      const finished: string[] = [];
      for (const [id, p] of Object.entries(res.progress ?? {})) {
        const seat = seatOf.get(id);
        if (!seat || !p || p.error || !p.total) continue;
        counts[seat] = `${p.done ?? 0}/${p.total}`;
        if ((p.done ?? 0) >= p.total) finished.push(seat);
      }
      setProgress((prev) => ({ ...prev, ...counts }));
      if (finished.length) setStates((s) => ({ ...s, ...Object.fromEntries(finished.map((n) => [n, "done" as const])) }));
    };
    void readProgress();
    let pending: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeAgentEvents((event) => {
      if (event.type === "linked_agent" && event.child_conv_id && names.includes(str(event.title)) && !chats[str(event.title)]) {
        setChats((c) => ({ ...c, [str(event.title)]: event.child_conv_id! }));
        return;
      }
      if (PLAN_EVENTS.has(event.type)) {
        if (!pending) pending = setTimeout(() => ((pending = null), void readProgress()), PLAN_EVENT_COALESCE_MS);
        return;
      }
      const seat = event.conv_id ? seatOf.get(event.conv_id) : undefined;
      if (!seat) return;
      setStates((s) => {
        const next = nextSeatState(s[seat] ?? "created", event);
        return next === s[seat] ? s : { ...s, [seat]: next };
      });
    });
    return () => {
      live = false;
      if (pending) clearTimeout(pending);
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [built, chatKey, names]);

  if (!card) return null;

  const build = () => {
    if (overlaps.length) return;
    const confirm: SwarmConfirm = { goal, jobs: jobList, ...answers, agents: "auto", edits, confirm: true };
    setBuilt(true);
    if (onBuild) onBuild(confirm);
    else {
      const text = `Build the swarm exactly as previewed: call ducky_swarm_create with these arguments: ${JSON.stringify(confirm)}`;
      cardRef.current?.dispatchEvent(new CustomEvent(SWARM_CARD_EVENT, { detail: { action: "build", text }, bubbles: true }));
    }
  };

  const doneCount = names.filter((n) => states[n] === "done").length;
  const title = built ? `Swarm: ${goal || "swarm"} · ${doneCount}/${names.length} done` : `Build swarm: ${goal || "swarm"}`;

  return (
    <section ref={cardRef} className={`swarm-card swarm-builder${built ? " swarm-builder--built" : ""}`} aria-label={title}>
      <header className="swarm-card-title">{title}</header>
      {built ? null : (
        <div className="swarm-builder-sliders">
          <Slider label="Detail" value={answers.detail} lim={LIMITS.detail} text={DETAIL_NAMES[answers.detail - 1]} onChange={(n) => move({ detail: n })} />
          <Slider label="Max agents" value={answers.max_agents} lim={LIMITS.max_agents} text={String(answers.max_agents)} onChange={(n) => move({ max_agents: n })} />
          <Slider label="Per group" value={answers.per_group} lim={LIMITS.per_group} text={String(answers.per_group)} onChange={(n) => move({ per_group: n })} />
        </div>
      )}
      {built ? null : <div className="swarm-card-summary" aria-live="polite">{countsLine(preview, answers.detail)}</div>}
      {error ? <div className="swarm-builder-error" role="alert" style={{ color: "var(--red)" }}>{error}</div> : null}
      {built ? (
        <div className="swarm-card-tree" role="tree" aria-label="Team">
          <Tree rows={rows} states={states} progress={progress} />
        </div>
      ) : (
        <>
          {treeData ? <SwarmTree data={treeData} overlaps={overlapSeats} /> : null}
          <div className="swarm-builder-editors" aria-label="Edit the team">
            {draft.groups.map((g) => (
              <GroupEditor key={`g:${g.group}`} group={g} onEdit={edit} />
            ))}
            {draft.seats.map((s) => (
              <SeatEditor key={`s:${s.name}`} seat={s} onEdit={edit} overlaps={overlaps} />
            ))}
          </div>
          {overlaps.length ? (
            <ul className="swarm-builder-overlaps" aria-label="Lane overlaps" style={{ color: "var(--red)" }}>
              {overlaps.map((o) => (
                <li key={`${o.seat}|${o.other}|${o.path}`}>{overlapNotes(o.seat, [o])[0]}</li>
              ))}
            </ul>
          ) : null}
          <div className="swarm-card-actions">
            <button type="button" className="swarm-card-btn swarm-card-btn--primary" disabled={overlaps.length > 0} onClick={build}>
              Build
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/** Tool-presenter view: ducky_swarm_create's swarm_builder result with the call's own jobs. */
export function SwarmBuilderToolView({ arguments: args, resultText }: { arguments: Record<string, unknown>; resultText: string }) {
  return <SwarmBuilderCard payload={resultText} jobs={args?.jobs} />;
}
