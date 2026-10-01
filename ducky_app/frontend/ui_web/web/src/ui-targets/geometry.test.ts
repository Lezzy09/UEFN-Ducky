import { describe, expect, it } from "vitest";
import { clipOutside, holeFor, modeFor, offscreenSide, placeCard, unionBox } from "./geometry";

const VIEW = { width: 1000, height: 800 };

describe("spotlight geometry", () => {
  it("pads the hole, keeps it at least 24px, makes circles square", () => {
    expect(holeFor({ left: 100, top: 100, width: 50, height: 20 })).toEqual({ left: 92, top: 92, width: 66, height: 36, radius: "8px" });
    expect(holeFor({ left: 100, top: 100, width: 20, height: 10 }, "circle")).toMatchObject({ width: 36, height: 36, radius: "50%" });
    expect(holeFor({ left: 0, top: 0, width: 2, height: 2 }, "rect", 0)).toMatchObject({ width: 24, height: 24 });
    expect(modeFor({ left: 0, top: 0, width: 28, height: 28 })).toBe("circle");
    expect(modeFor({ left: 0, top: 0, width: 200, height: 28 })).toBe("rect");
  });

  it("wraps several targets in one box", () => {
    expect(unionBox([{ left: 10, top: 10, width: 10, height: 10 }, { left: 50, top: 5, width: 10, height: 40 }])).toEqual({ left: 10, top: 5, width: 50, height: 40 });
    expect(unionBox([{ left: 0, top: 0, width: 0, height: 0 }])).toBeNull();
  });

  it("puts the card above when asked and there is room, else below; centered with no hole", () => {
    const hole = { left: 400, top: 400, width: 100, height: 40 };
    const above = placeCard(hole, 300, 150, "above", 12, VIEW);
    expect(above.side).toBe("above");
    expect(above.y).toBe(400 - 150 - 12);
    expect(above.arrowX).toBeCloseTo(150);
    const nearTop = placeCard({ left: 400, top: 40, width: 100, height: 40 }, 300, 150, "above", 12, VIEW);
    expect(nearTop.side).toBe("below");
    expect(placeCard(hole, 300, 150, "below", 12, VIEW).side).toBe("below");
    const centered = placeCard(null, 300, 150, "above", 12, VIEW);
    expect(centered.side).toBe("center");
    expect(centered.x).toBe(350);
  });

  it("keeps the card on screen near the edges", () => {
    const right = placeCard({ left: 980, top: 400, width: 10, height: 10 }, 300, 100, "above", 12, VIEW);
    expect(right.x).toBe(1000 - 300 - 12);
    expect(right.arrowX).toBeLessThanOrEqual(300 - 16);
  });

  it("cuts a click-through hole and says which way an off-screen target went", () => {
    expect(clipOutside({ left: 1, top: 2, width: 3, height: 4 })).toBe("polygon(evenodd, 0% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%, 1px 2px, 1px 6px, 4px 6px, 4px 2px, 1px 2px)");
    expect(offscreenSide({ left: 10, top: -100, width: 10, height: 50 }, VIEW)).toBe("up");
    expect(offscreenSide({ left: 10, top: 900, width: 10, height: 50 }, VIEW)).toBe("down");
    expect(offscreenSide({ left: -50, top: 10, width: 10, height: 50 }, VIEW)).toBe("left");
    expect(offscreenSide({ left: 10, top: 10, width: 10, height: 50 }, VIEW)).toBe("");
  });
});
