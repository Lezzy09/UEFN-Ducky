export type FileDiffLine =
  | { kind: "context"; line: number; text: string }
  | { kind: "add"; line: number; text: string }
  | { kind: "remove"; line: number; text: string };

export interface FileDiffHunk {
  id: string;
  lines: FileDiffLine[];
}

export interface FileEditDiffSummary {
  path: string;
  fileName: string;
  linesAdded: number;
  linesRemoved: number;
  hunks: FileDiffHunk[];
  isCreate: boolean;
}

const CONTEXT_LINES = 2;
/**
 * The line-matching table is changed-lines-before × changed-lines-after cells. Past this, a
 * whole-file rewrite shows as removed-then-added instead of freezing the chat on a huge table.
 */
const MAX_LCS_CELLS = 4_000_000;

function fileNameFromPath(path: string): string {
  const norm = path.replace(/\\/g, "/");
  const parts = norm.split("/");
  return parts[parts.length - 1] || path;
}

/** Build hunks with limited context — Cursor-style collapsed diff regions. */
export function buildFileEditDiff(
  path: string,
  before: string,
  after: string,
  linesAdded: number,
  linesRemoved: number,
  kind: "write" | "create" = "write",
): FileEditDiffSummary {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  if (kind === "create") {
    return {
      path,
      fileName: fileNameFromPath(path),
      linesAdded,
      linesRemoved,
      hunks: [{ id: "hunk-0", lines: afterLines.map((text, idx) => ({ kind: "add" as const, line: idx + 1, text })) }],
      isCreate: true,
    };
  }

  // Lines the edit didn't touch at the top and bottom need no matching.
  let top = 0;
  while (top < beforeLines.length && top < afterLines.length && beforeLines[top] === afterLines[top]) top += 1;
  let bottom = 0;
  while (
    bottom < beforeLines.length - top &&
    bottom < afterLines.length - top &&
    beforeLines[beforeLines.length - 1 - bottom] === afterLines[afterLines.length - 1 - bottom]
  ) bottom += 1;
  const n = beforeLines.length - bottom;
  const m = afterLines.length - bottom;

  const raw: FileDiffLine[] = [];
  for (let k = 0; k < top; k += 1) raw.push({ kind: "context", line: k + 1, text: afterLines[k] });
  let i = top;
  let j = top;
  let afterLine = top + 1;
  let beforeLine = top + 1;

  const rows = n - top;
  const cols = m - top;
  if (rows > 0 && cols > 0 && rows * cols <= MAX_LCS_CELLS) {
    // dp[(i-top) * (cols+1) + (j-top)] = longest common run from i, j to the end of the middle.
    const w = cols + 1;
    const dp = new Uint32Array((rows + 1) * w);
    for (let a = rows - 1; a >= 0; a -= 1) {
      for (let b = cols - 1; b >= 0; b -= 1) {
        dp[a * w + b] = beforeLines[top + a] === afterLines[top + b]
          ? dp[(a + 1) * w + b + 1] + 1
          : Math.max(dp[(a + 1) * w + b], dp[a * w + b + 1]);
      }
    }
    while (i < n && j < m) {
      const a = i - top;
      const b = j - top;
      if (beforeLines[i] === afterLines[j]) {
        raw.push({ kind: "context", line: afterLine, text: afterLines[j] });
        i += 1;
        j += 1;
        afterLine += 1;
        beforeLine += 1;
      } else if (dp[(a + 1) * w + b] >= dp[a * w + b + 1]) {
        raw.push({ kind: "remove", line: beforeLine, text: beforeLines[i] });
        i += 1;
        beforeLine += 1;
      } else {
        raw.push({ kind: "add", line: afterLine, text: afterLines[j] });
        j += 1;
        afterLine += 1;
      }
    }
  }
  while (i < n) {
    raw.push({ kind: "remove", line: beforeLine, text: beforeLines[i] });
    i += 1;
    beforeLine += 1;
  }
  while (j < m) {
    raw.push({ kind: "add", line: afterLine, text: afterLines[j] });
    j += 1;
    afterLine += 1;
  }
  for (let k = 0; k < bottom; k += 1) raw.push({ kind: "context", line: afterLine + k, text: afterLines[m + k] });

  const changeIdx = raw
    .map((line, idx) => (line.kind === "context" ? -1 : idx))
    .filter((idx) => idx >= 0);
  const keep = new Set<number>();
  for (const idx of changeIdx) {
    for (let k = Math.max(0, idx - CONTEXT_LINES); k <= Math.min(raw.length - 1, idx + CONTEXT_LINES); k += 1) {
      keep.add(k);
    }
  }
  const filtered = raw.filter((_, idx) => keep.has(idx));

  const hunks: FileDiffHunk[] = [];
  let current: FileDiffLine[] = [];
  let hunkId = 0;
  for (const line of filtered) {
    if (line.kind === "context" && current.length > 0 && current[current.length - 1]?.kind !== "context") {
      hunks.push({ id: `hunk-${hunkId}`, lines: current });
      hunkId += 1;
      current = [line];
      continue;
    }
    current.push(line);
  }
  if (current.length > 0) {
    hunks.push({ id: `hunk-${hunkId}`, lines: current });
  }

  return {
    path,
    fileName: fileNameFromPath(path),
    linesAdded,
    linesRemoved,
    hunks,
    isCreate: false,
  };
}
