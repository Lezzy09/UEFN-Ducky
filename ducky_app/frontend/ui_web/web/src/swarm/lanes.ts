/** Lane overlap check for the swarm card: Build stays disabled while any seats share a path. */

export interface LaneSeat {
  name: string;
  paths: string[];
}

export interface LaneOverlap {
  seat: string;
  other: string;
  /** The narrower of the two clashing paths, e.g. "ui/index.html". */
  path: string;
}

/** The part of a glob before its first wildcard; the whole path when it has none. */
function fixedPart(glob: string): { prefix: string; wild: boolean } {
  const norm = glob.trim().replace(/\\/g, "/");
  const at = norm.search(/[*?[{]/);
  return at < 0 ? { prefix: norm, wild: false } : { prefix: norm.slice(0, at), wild: true };
}

/** The narrower path when `a` and `b` can match the same file, else null.
 *  ponytail: prefix test only, so "src/*.ts" vs "src/x.py" counts as a clash; a real glob
 *  intersection if false alarms bother anyone. */
export function pathsOverlap(a: string, b: string): string | null {
  const pa = fixedPart(a);
  const pb = fixedPart(b);
  if (!pa.wild && !pb.wild) return pa.prefix === pb.prefix ? a : null;
  if (pa.wild && pb.prefix.startsWith(pa.prefix)) return b;
  if (pb.wild && pa.prefix.startsWith(pb.prefix)) return a;
  return null;
}

export function laneOverlaps(seats: LaneSeat[]): LaneOverlap[] {
  const out: LaneOverlap[] = [];
  seats.forEach((s, i) => {
    for (const o of seats.slice(i + 1)) {
      for (const a of s.paths) {
        const path = o.paths.map((b) => pathsOverlap(a, b)).find(Boolean);
        if (path) {
          out.push({ seat: s.name, other: o.name, path });
          break;
        }
      }
    }
  });
  return out;
}

/** "Store lead ⚠ lane overlaps Plugin core: ui/index.html" lines for one seat. */
export function overlapNotes(seat: string, overlaps: LaneOverlap[]): string[] {
  return overlaps
    .filter((o) => o.seat === seat || o.other === seat)
    .map((o) => `${seat} ⚠ lane overlaps ${o.seat === seat ? o.other : o.seat}: ${o.path}`);
}
