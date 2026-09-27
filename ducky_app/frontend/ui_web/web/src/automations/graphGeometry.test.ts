import { describe, expect, it } from "vitest";
import { arrangeGraph, nodeWidth, portPoint, zoomAt } from "./graphGeometry";

const node = { id: "a", type: "flow.wait", x: 100, y: 50, config: {}, width: 480 };

describe("graph geometry", () => {
  it("attaches connections to the exact edge after resizing and collapsing", () => {
    expect(portPoint(node, "out", true)).toEqual({ x: 580, y: 88 });
    expect(portPoint(node, "in", true)).toEqual({ x: 100, y: 88 });
    expect(portPoint(node, "out", false)).toEqual({ x: 300, y: 88 });
    expect(nodeWidth({ ...node, width: 900 }, true)).toBe(720);
    expect(nodeWidth({ ...node, width: 50 }, true)).toBe(280);
  });
  it("keeps the world point under the cursor during zoom", () => {
    const next = zoomAt({ x: 30, y: 60 }, 0.5, 1, { x: 180, y: 160 });
    expect((180 - next.x) / 1).toBe((180 - 30) / 0.5);
    expect((160 - next.y) / 1).toBe((160 - 60) / 0.5);
  });
  it("spaces a branch and join without changing connections or configuration", () => {
    const graph = { nodes: [node, { ...node, id: "b" }, { ...node, id: "c" }, { ...node, id: "d" }], edges: [
      { source: "a", target: "b", kind: "true" }, { source: "a", target: "c", kind: "false" },
      { source: "b", target: "d", kind: "main" }, { source: "c", target: "d", kind: "main" },
    ] };
    const arranged = arrangeGraph(graph);
    expect(arranged.nodes.map((n) => [n.x, n.y])).toEqual([[0, 0], [280, 0], [280, 140], [560, 0]]);
    expect(arranged.edges).toEqual(graph.edges);
    expect(arranged.nodes[0].width).toBe(480);
  });
  it("terminates on cycles and places each cyclic node separately", () => {
    const result = arrangeGraph({ nodes: [node, { ...node, id: "b" }], edges: [
      { source: "a", target: "b", kind: "main" }, { source: "b", target: "a", kind: "main" },
    ] });
    expect(result.nodes[0].y).not.toBe(result.nodes[1].y);
  });
  it("leaves enough room for an expanded, resized node", () => {
    const result = arrangeGraph({ nodes: [node, { ...node, id: "b" }], edges: [{ source: "a", target: "b", kind: "main" }] }, "a");
    expect(result.nodes[1].x).toBe(560);
  });
});
