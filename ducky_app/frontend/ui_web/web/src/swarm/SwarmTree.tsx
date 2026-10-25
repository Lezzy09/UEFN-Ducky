import { useLayoutEffect, useMemo, useRef } from "react";
import { RichChart } from "../components/rich-content/RichChart";
import type { ChartSpec, TreeNode } from "../components/rich-content/RichChart";
import { DuckyAvatar } from "../components/ducky/DuckyAvatars";
import { countSeats } from "../components/tool-presenters/SwarmCard";
import type { SwarmCardData, SwarmGroup, SwarmSeat } from "../components/tool-presenters/SwarmCard";

// The swarm as a tree of duckies: lead → groups → seats, drawn by RichChart's
// tree. Nodes are tagged after paint (TreeChart places them post-order):
// muted groups, seats that start later (dashed) and seats whose lanes overlap (red).

export interface SwarmTreeProps {
  data: SwarmCardData;
  /** The lead's model, shown on the root. */
  leadModel?: string;
  /** Seat names whose lanes overlap another seat's (from lanes.ts). */
  overlaps?: Iterable<string>;
  /** Seat or group name → what it waits for ("" = just later). A later group makes its seats later. */
  later?: Record<string, string>;
}

/** "claude:claude-opus-5-5" → "Opus 5.5"; anything else as given without its provider. */
export function modelChip(model: string): string {
  const id = model.includes(":") ? model.slice(model.indexOf(":") + 1) : model;
  const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(id);
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}` : id;
}

type Mark = "seat" | "group" | "root";
type Draw = { key: string; label: string; color: string; mark: Mark; classes: string[]; children: Draw[] };

function waits(name: string, later: Record<string, string>): string | null {
  if (!(name in later)) return null;
  return later[name] ? `waits ${later[name]}` : "starts later";
}

function seatDraw(s: SwarmSeat, overlap: Set<string>, later: Record<string, string>, groupLater: boolean): Draw {
  const wait = waits(s.name, later);
  const isLater = groupLater || wait !== null;
  const bad = overlap.has(s.name);
  const classes = [isLater && "swarm-tree-node--later", bad && "swarm-tree-node--overlap"].filter(Boolean) as string[];
  return {
    key: s.key,
    label: [s.name, s.model && modelChip(s.model), wait].filter(Boolean).join(" · "),
    color: bad ? "red" : "green",
    mark: "seat",
    classes,
    children: [],
  };
}

function groupDraw(g: SwarmGroup, overlap: Set<string>, later: Record<string, string>, parentLater: boolean): Draw {
  const wait = waits(g.name, later);
  const isLater = parentLater || wait !== null;
  const n = countSeats(g);
  return {
    key: g.key,
    label: [`${g.name} (${n})`, g.muted && "MUTED", wait].filter(Boolean).join(" · "),
    color: g.muted ? "amber" : "purple",
    mark: "group",
    classes: [g.muted && "swarm-tree-node--muted", isLater && "swarm-tree-node--later"].filter(Boolean) as string[],
    children: [
      ...g.groups.map((sub) => groupDraw(sub, overlap, later, isLater)),
      ...g.seats.map((s) => seatDraw(s, overlap, later, isLater)),
    ],
  };
}

function toTreeNode(d: Draw): TreeNode {
  return d.children.length ? { label: d.label, color: d.color, children: d.children.map(toTreeNode) } : { label: d.label, color: d.color };
}

function postOrder(d: Draw, out: Draw[] = []): Draw[] {
  d.children.forEach((c) => postOrder(c, out));
  out.push(d);
  return out;
}

function seatsOf(g: { seats: SwarmSeat[]; groups: SwarmGroup[] }): SwarmSeat[] {
  return [...g.seats, ...g.groups.flatMap(seatsOf)];
}

export function SwarmTree({ data, leadModel = "", overlaps, later = {} }: SwarmTreeProps) {
  const overlapKey = [...(overlaps ?? [])].join("\n");
  const laterKey = JSON.stringify(later);
  const root = useMemo<Draw>(() => {
    const overlap = new Set(overlapKey ? overlapKey.split("\n") : []);
    const wait: Record<string, string> = JSON.parse(laterKey);
    return {
      key: "root",
      label: leadModel ? `Lead (${modelChip(leadModel)})` : "Lead",
      color: "blue",
      mark: "root",
      classes: [],
      children: [
        ...data.groups.map((g) => groupDraw(g, overlap, wait, false)),
        ...data.seats.map((s) => seatDraw(s, overlap, wait, false)),
      ],
    };
  }, [data, leadModel, overlapKey, laterKey]);
  const spec = useMemo<ChartSpec>(() => ({ type: "tree", title: "", root: toTreeNode(root) }), [root]);
  const order = useMemo(() => postOrder(root), [root]);

  const hostRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const marks = hostRef.current?.querySelectorAll("g.rich-chart-mark") ?? [];
    order.forEach((d, i) => {
      const el = marks[i];
      if (!el) return;
      el.setAttribute("data-swarm-key", d.key);
      el.setAttribute("class", ["rich-chart-mark", ...[...el.classList].filter((c) => c.startsWith("rich-c-")), "swarm-tree-node", `swarm-tree-node--${d.mark}`, ...d.classes].join(" "));
      // ponytail: dash set through CSSOM (CSP-safe), so the tree needs no stylesheet of its own.
      const rect = el.querySelector<SVGRectElement>("rect.rich-chart-node");
      if (rect) rect.style.strokeDasharray = d.classes.includes("swarm-tree-node--later") ? "4 3" : "";
    });
  });

  const seats = seatsOf(data);
  const byKey = new Map(order.map((d) => [d.key, d]));
  return (
    <div className="swarm-tree" aria-label="Swarm tree">
      <div ref={hostRef} className="swarm-tree-chart">
        <RichChart spec={spec} />
      </div>
      <ul className="swarm-tree-seats">
        {seats.map((s) => (
          <li key={s.key} className={["swarm-tree-seat", ...(byKey.get(s.key)?.classes ?? [])].join(" ")}>
            <DuckyAvatar styleId={s.profile} size={18} title={s.profile || s.name} />
            <span className="swarm-tree-seat-name">{s.name}</span>
            {s.model ? <span className="swarm-tree-model-chip">{modelChip(s.model)}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
