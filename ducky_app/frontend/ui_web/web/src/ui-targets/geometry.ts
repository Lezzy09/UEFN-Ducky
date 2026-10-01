/**
 * Shared spotlight geometry for tours and Show me: the highlighted hole around one or
 * more elements, where the explaining card goes, and the click-blocking clip with a
 * hole the target stays clickable through.
 */

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Hole extends Box {
  radius: string;
}

export type SpotMode = "rect" | "circle";

const MARGIN = 12;

/** The box around every rect (a group of nodes is shown as one). */
export function unionBox(rects: Array<Pick<DOMRect, "left" | "top" | "width" | "height">>): Box | null {
  const real = rects.filter((r) => r.width > 0 || r.height > 0);
  if (!real.length) return null;
  const left = Math.min(...real.map((r) => r.left));
  const top = Math.min(...real.map((r) => r.top));
  const right = Math.max(...real.map((r) => r.left + r.width));
  const bottom = Math.max(...real.map((r) => r.top + r.height));
  return { left, top, width: right - left, height: bottom - top };
}

/** The highlighted hole around a box: padded, at least 24px, round for circles. */
export function holeFor(box: Box, mode: SpotMode = "rect", pad = 8): Hole {
  const w = Math.max(24, box.width + pad * 2);
  const h = Math.max(24, box.height + pad * 2);
  if (mode === "circle") {
    const size = Math.max(w, h);
    return {
      left: box.left + box.width / 2 - size / 2,
      top: box.top + box.height / 2 - size / 2,
      width: size,
      height: size,
      radius: "50%",
    };
  }
  return { left: box.left - pad, top: box.top - pad, width: w, height: h, radius: "8px" };
}

/** Small round targets (icon buttons) get a circle; everything else a rounded box. */
export function modeFor(box: Box): SpotMode {
  return box.width <= 44 && box.height <= 44 ? "circle" : "rect";
}

export interface CardPlace {
  x: number;
  y: number;
  side: "above" | "below" | "center";
  /** Where the arrow meets the card, from the card's left edge. */
  arrowX: number;
}

/**
 * Where the explaining card goes. `prefer: "above"` puts it above the hole and only
 * drops below when there's no room; `"below"` the other way round. No hole: centered.
 */
export function placeCard(
  hole: Box | null,
  cardW: number,
  cardH: number,
  prefer: "above" | "below" = "below",
  gap = 12,
  viewport = { width: window.innerWidth, height: window.innerHeight },
): CardPlace {
  const vw = viewport.width;
  const vh = viewport.height;
  const w = Math.min(cardW, vw - MARGIN * 2);
  if (!hole) {
    return { x: Math.max(MARGIN, (vw - w) / 2), y: Math.max(MARGIN, vh * 0.3), side: "center", arrowX: w / 2 };
  }
  const center = hole.left + hole.width / 2;
  const x = Math.max(MARGIN, Math.min(center - w / 2, vw - w - MARGIN));
  const aboveY = hole.top - cardH - gap;
  const belowY = hole.top + hole.height + gap;
  const fitsAbove = aboveY >= MARGIN;
  const fitsBelow = belowY + cardH <= vh - MARGIN;
  let side: "above" | "below";
  if (prefer === "above") side = fitsAbove || !fitsBelow ? "above" : "below";
  else side = fitsBelow || !fitsAbove ? "below" : "above";
  let y = side === "above" ? aboveY : belowY;
  y = Math.max(MARGIN, Math.min(y, vh - cardH - MARGIN));
  const arrowX = Math.max(16, Math.min(center - x, w - 16));
  return { x, y, side, arrowX };
}

/** A clip-path that covers the whole screen except the hole (clicks pass through it). */
export function clipOutside(hole: Box): string {
  const x = hole.left;
  const y = hole.top;
  const x2 = hole.left + hole.width;
  const y2 = hole.top + hole.height;
  return `polygon(evenodd, 0% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%, ${x}px ${y}px, ${x}px ${y2}px, ${x2}px ${y2}px, ${x2}px ${y}px, ${x}px ${y}px)`;
}

/** Which way the hole went when it is off screen, or "" when part of it is in view. */
export function offscreenSide(hole: Box, viewport = { width: window.innerWidth, height: window.innerHeight }): "" | "up" | "down" | "left" | "right" {
  if (hole.top + hole.height <= 0) return "up";
  if (hole.top >= viewport.height) return "down";
  if (hole.left + hole.width <= 0) return "left";
  if (hole.left >= viewport.width) return "right";
  return "";
}
