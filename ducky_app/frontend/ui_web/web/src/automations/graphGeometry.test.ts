import { describe, expect, it } from "vitest";
import { clampZoom, fitCamera, gridScale, groupTitleScale, portPoint, wirePath, zoomAt } from "./graphGeometry";

const node = { id: "a", type: "flow.wait", x: 100, y: 50, config: {}, width: 480 };

describe("graph geometry", () => {
  it("attaches connections to the card edges under the title bar, whatever width was saved", () => {
    expect(portPoint(node, "out")).toEqual({ x: 340, y: 102 });
    expect(portPoint(node, "in")).toEqual({ x: 100, y: 102 });
    expect(portPoint(node, "out", true)).toEqual({ x: 340, y: 86 });  // zoomed out: the middle of the thin card
  });
  it("zooms out to 5% and in to 400%", () => {
    expect(clampZoom(0.01)).toBe(0.05);
    expect(clampZoom(0.1)).toBe(0.1);
    expect(clampZoom(9)).toBe(4);
  });
  it("keeps group titles readable but small when zoomed out, and steps the grid up", () => {
    expect(groupTitleScale(1)).toBe(1);
    expect(16 * groupTitleScale(0.4) * 0.4).toBeCloseTo(10);  // 10px on screen, not 16
    expect(16 * groupTitleScale(0.1) * 0.1).toBeCloseTo(10);
    expect(gridScale(1)).toBe(1);
    expect(gridScale(0.1) * 128).toBeGreaterThanOrEqual(24);
  });
  it("centres a box in the view, capped for a single node", () => {
    const view = { x: 100, y: 50, width: 800, height: 400 };
    const one = fitCamera({ x: 0, y: 0, width: 200, height: 82 }, view, 1.5);
    expect(one.zoom).toBe(1.5);
    expect(one.x + 100 * one.zoom).toBe(500);  // the middle of the node lands in the middle of the view
    expect(one.y + 41 * one.zoom).toBe(250);
    const wide = fitCamera({ x: -1000, y: 0, width: 16000, height: 100 }, view, 1);
    expect(wide.zoom).toBe(0.05);
  });
  it("bends a wire out to the right and into the left", () => {
    expect(wirePath(0, 0, 200, 40)).toBe("M 0 0 C 100 0, 100 40, 200 40");
    expect(wirePath(200, 0, 0, 0)).toBe("M 200 0 C 300 0, -100 0, 0 0");
  });
  it("keeps the world point under the cursor during zoom", () => {
    const next = zoomAt({ x: 30, y: 60 }, 0.5, 1, { x: 180, y: 160 });
    expect((180 - next.x) / 1).toBe((180 - 30) / 0.5);
    expect((160 - next.y) / 1).toBe((160 - 60) / 0.5);
  });
});
