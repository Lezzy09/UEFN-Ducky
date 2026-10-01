import { useRef, useState, type CSSProperties } from "react";
import { DropdownPanel } from "../components/DropdownPanel";
import { Icons } from "../icons/Icons";
import type { AutomationGraphDto, AutomationGraphGroupDto, AutomationGraphNodeDto, AutomationNodeDto } from "../types/panel";
import { GroupIcon, NodeIcon, nodeLabel, nodeRole } from "./NodeVisuals";
import { groupLocked, groupMembers, nodeLocked } from "./workflowGroups";

/** Left to right, then top to bottom: roughly the order it runs. */
const byPlace = (a: AutomationGraphNodeDto, b: AutomationGraphNodeDto) => a.x - b.x || a.y - b.y;

/** The header's outline: every group (nested ones inside) and node of the open workflow
 *  as a tree. Picking one selects it and brings it into view. */
export function WorkflowOutline({ graph, byType, faces, selectedIds, onPick, buttonRef }: {
  graph: AutomationGraphDto;
  byType: Map<string, AutomationNodeDto>;
  faces: Record<string, string>;
  selectedIds: string[];
  /** ids = the node, or every node of the group; key = the details tab to show. */
  onPick: (ids: string[], key: string) => void;
  buttonRef?: (el: HTMLButtonElement | null) => void;
}) {
  const anchor = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const groups = graph.groups || [];
  const grouped = new Set(groups.flatMap((group) => group.node_ids));
  const pick = (ids: string[], key: string) => { setOpen(false); onPick(ids, key); };

  const nodeRow = (node: AutomationGraphNodeDto, depth: number) => (
    <li key={node.id}>
      <button type="button" className={`aw-outline-row aw-outline-row--${nodeRole(node, byType.get(node.type))}${selectedIds.includes(node.id) ? " is-selected" : ""}`}
        style={{ "--aw-level": depth } as CSSProperties} onClick={() => pick([node.id], `node:${node.id}`)}>
        <NodeIcon meta={byType.get(node.type)} node={node} faces={faces} />
        <span className="aw-outline-name">{nodeLabel(node, byType.get(node.type))}</span>
        {nodeLocked(graph, node.id) ? <span className="aw-outline-lock" role="img" aria-label="Locked"><Icons.Lock /></span> : null}
      </button>
    </li>
  );
  /** Where a group starts: its leftmost (then topmost) node. */
  const groupPlace = (group: AutomationGraphGroupDto) => {
    const nodes = graph.nodes.filter((node) => groupMembers(groups, group.id).includes(node.id)).sort(byPlace);
    return nodes[0] || { x: Infinity, y: Infinity };
  };
  /** Groups and loose nodes of one level, in the order the flow reads (left to right). */
  const level = (inner: AutomationGraphGroupDto[], own: AutomationGraphNodeDto[], depth: number) =>
    [...inner.map((group) => ({ at: groupPlace(group), row: () => groupRow(group, depth) })), ...own.map((node) => ({ at: node, row: () => nodeRow(node, depth) }))]
      .sort((a, b) => a.at.x - b.at.x || a.at.y - b.at.y).map((item) => item.row());
  const groupRow = (group: AutomationGraphGroupDto, depth: number): React.ReactNode => {
    const members = groupMembers(groups, group.id);
    const inner = groups.filter((item) => item.parent_id === group.id);
    const own = graph.nodes.filter((node) => group.node_ids.includes(node.id));
    return (
      <li key={group.id}>
        <button type="button" className={`aw-outline-row aw-outline-row--group${members.length && members.every((id) => selectedIds.includes(id)) ? " is-selected" : ""}`}
          style={{ "--aw-level": depth } as CSSProperties} onClick={() => pick(members, `group:${group.id}`)}>
          <GroupIcon icon={group.icon} />
          <span className="aw-outline-name">{group.name}</span>
          {groupLocked(groups, group.id) ? <span className="aw-outline-lock" role="img" aria-label="Locked"><Icons.Lock /></span> : null}
          <small>{members.length}</small>
        </button>
        <ul className="aw-outline-children" style={{ "--aw-level": depth } as CSSProperties}>
          {level(inner, own, depth + 1)}
        </ul>
      </li>
    );
  };
  const loose = graph.nodes.filter((node) => !grouped.has(node.id));
  const top = groups.filter((group) => !group.parent_id || !groups.some((item) => item.id === group.parent_id));

  return <>
    <button ref={(el) => { anchor.current = el; buttonRef?.(el); }} type="button" className="aw-outline-button" aria-label="Outline" aria-haspopup="dialog" aria-expanded={open}
      title="Outline: every group and node in this workflow" onClick={() => setOpen((value) => !value)}>
      <Icons.Outline />
    </button>
    <DropdownPanel anchorRef={anchor} open={open} onClose={() => setOpen(false)} width={320} idealHeight={520} placement="top">
      <div className="aw-outline" role="dialog" aria-label="Outline">
        <div className="aw-outline-head"><strong>Outline</strong><small>{graph.nodes.length} node{graph.nodes.length === 1 ? "" : "s"} · {groups.length} group{groups.length === 1 ? "" : "s"}</small></div>
        {graph.nodes.length ? <ul className="aw-outline-tree">
          {level(top, loose, 0)}
        </ul> : <p className="aw-outline-empty">No nodes yet. Right-click the canvas to add one.</p>}
      </div>
    </DropdownPanel>
  </>;
}
