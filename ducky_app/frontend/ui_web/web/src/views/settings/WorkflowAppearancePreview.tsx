import { portPoint, wirePath } from "../../automations/graphGeometry";
import type { AutomationGraphNodeDto } from "../../types/panel";

const NODES: Array<AutomationGraphNodeDto & { role: string; sub: string }> = [
  { id: "a", type: "start.chat", x: 0, y: 70, config: {}, label: "Chat input", role: "starter", sub: "Message from your chat" },
  { id: "b", type: "flow.branch", x: 280, y: 70, config: {}, label: "Island ready?", role: "logic", sub: "data.ready equals true" },
  { id: "c", type: "tool.call", x: 560, y: 0, config: {}, label: "Start game", role: "action", sub: "Start the island session" },
  { id: "d", type: "pipeline.finish", x: 560, y: 140, config: {}, label: "Return to user", role: "end", sub: "Tell the chat it isn't ready" },
];
const EDGES = [
  { source: "a", target: "b", kind: "main", from: "starter" },
  { source: "b", target: "c", kind: "true", from: "logic" },
  { source: "b", target: "d", kind: "false", from: "logic" },
];

/** The canvas in miniature, drawn with the editor's own classes so every token shows. */
export function WorkflowAppearancePreview() {
  const at = (id: string) => NODES.find((node) => node.id === id)!;
  return (
    <div className="aw-preview" role="img" aria-label="Workflow canvas preview">
      <div className="aw-preview-world">
        <svg className="aw-wires" width={780} height={240}>
          {EDGES.map((edge) => {
            const from = portPoint(at(edge.source), "out");
            const to = portPoint(at(edge.target), "in");
            const d = wirePath(from.x, from.y, to.x, to.y);
            return (
              <g key={edge.target} className={`aw-edge aw-edge--${edge.kind} aw-edge--from-${edge.from}`}>
                <path className="aw-edge-glow" d={d} />
                <path className={`aw-wire aw-wire--${edge.kind}`} d={d} />
                <path className="aw-edge-arrow" d="M -4 -3 L 4 0 L -4 3 Z">
                  <animateMotion dur="3.5s" repeatCount="indefinite" rotate="auto" path={d} />
                </path>
              </g>
            );
          })}
        </svg>
        {NODES.map((node) => (
          <div key={node.id} className={`aw-node aw-node--${node.role}${node.id === "b" ? " is-selected" : ""}`} style={{ left: node.x, top: node.y }}>
            <div className="aw-node-card">
              <div className="aw-node-title"><strong>{node.label}</strong></div>
              <div className="aw-node-body"><span className="aw-node-sub">{node.sub}</span></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
