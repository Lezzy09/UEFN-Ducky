export const RAIL_EDGE_PX = 24;

/** Share of a phone screen a drawer may cover (the CSS caps it at 85vw too). */
export const OVERLAY_DRAWER_MAX_SHARE = 0.85;

/** A drawer's width on a phone: its desktop width, never more than 85% of the screen. */
export function overlayDrawerWidth(width: number, viewportWidth = typeof window === "undefined" ? Infinity : window.innerWidth): number {
  return Math.min(width, Math.round(viewportWidth * OVERLAY_DRAWER_MAX_SHARE));
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

/** translateX of the rail: 0 = fully on-screen. Left hides at -width, right at +width. */
export function swipeTranslateX(
  side: "left" | "right",
  open: boolean,
  dx: number,
  width: number,
): number {
  if (width <= 0) return open ? 0 : side === "left" ? -1 : 1;
  if (side === "left") {
    return open ? clamp(dx, -width, 0) : clamp(dx, 0, width) - width;
  }
  return open ? clamp(dx, 0, width) : clamp(dx, -width, 0) + width;
}

export function swipeShouldOpen(
  side: "left" | "right",
  tx: number,
  width: number,
  vx: number,
): boolean {
  if (width <= 0) return false;
  if (side === "left") {
    if (vx > 0.35) return true;
    if (vx < -0.35) return false;
    return tx + width > width / 2;
  }
  if (vx < -0.35) return true;
  if (vx > 0.35) return false;
  return width - tx > width / 2;
}

export function swipeSideFromPoint(
  x: number,
  layoutLeft: number,
  layoutRight: number,
  leftOpen: boolean,
  rightOpen: boolean,
  leftEnabled: boolean,
  rightEnabled: boolean,
  leftWidth: number,
  rightWidth: number,
): "left" | "right" | null {
  const fromLeft = x - layoutLeft;
  const fromRight = layoutRight - x;
  if (leftOpen && leftEnabled && fromLeft <= leftWidth) return "left";
  if (rightOpen && rightEnabled && fromRight <= rightWidth) return "right";
  if (!leftOpen && leftEnabled && fromLeft <= RAIL_EDGE_PX) return "left";
  if (!rightOpen && rightEnabled && fromRight <= RAIL_EDGE_PX) return "right";
  return null;
}
