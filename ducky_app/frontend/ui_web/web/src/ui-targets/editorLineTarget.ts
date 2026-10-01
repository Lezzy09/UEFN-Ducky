/**
 * Show me / tours on a line of code: `editor.line.<path>:<line>`. Going there opens the
 * file and centers the line; the highlight sits on a small anchor laid over that line, so
 * it follows the editor's scrolling.
 */
import { getQuickOpenEditor } from "../components/quick-open/quickOpenEditorBridge";
import { requestOpenProjectFile } from "../navigation/openChatReference";
import { registerTargetResolver } from "./resolve";

const PREFIX = "editor.line.";

function parse(id: string): { path: string; line: number } | null {
  const rest = id.slice(PREFIX.length);
  const at = rest.lastIndexOf(":");
  if (at <= 0) return null;
  const line = Number(rest.slice(at + 1));
  return Number.isFinite(line) && line > 0 ? { path: rest.slice(0, at).replace(/\\/g, "/"), line: Math.floor(line) } : null;
}

const norm = (path: string) => path.replace(/\\/g, "/").toLowerCase();
/** The same file, whether one path is relative and the other absolute. */
const same = (a: string, b: string) => !!a && !!b && (norm(a).endsWith(norm(b)) || norm(b).endsWith(norm(a)));

function anchorFor(path: string, line: number): HTMLElement | null {
  const ctx = getQuickOpenEditor();
  if (!ctx || !same(ctx.path, path)) return null;
  const host = ctx.editor.getDomNode();
  const pos = ctx.editor.getScrolledVisiblePosition({ lineNumber: line, column: 1 });
  if (!host || !pos) return null;
  let anchor = host.querySelector<HTMLElement>(":scope > .showme-line-anchor");
  if (!anchor) {
    anchor = document.createElement("div");
    anchor.className = "showme-line-anchor";
    anchor.style.cssText = "position:absolute;pointer-events:none;left:0;";
    host.style.position ||= "relative";
    host.append(anchor);
  }
  const layout = ctx.editor.getLayoutInfo();
  anchor.style.top = `${pos.top}px`;
  anchor.style.left = `${layout.contentLeft}px`;
  anchor.style.width = `${Math.max(80, layout.contentWidth - 24)}px`;
  anchor.style.height = `${pos.height}px`;
  return anchor;
}

export function installEditorLineTargets(): () => void {
  return registerTargetResolver(PREFIX, {
    find: (id) => {
      const at = parse(id);
      return at ? anchorFor(at.path, at.line) : null;
    },
    reveal: async (id) => {
      const at = parse(id);
      if (!at) return;
      const ctx = getQuickOpenEditor();
      if (!ctx || !same(ctx.path, at.path)) {
        requestOpenProjectFile(at.path);
        for (let i = 0; i < 40; i++) {
          await new Promise((r) => globalThis.setTimeout(r, 100));
          const now = getQuickOpenEditor();
          if (now && same(now.path, at.path)) break;
        }
      }
      try {
        getQuickOpenEditor()?.editor.revealLineInCenter(at.line);
      } catch {
        /* editor closed */
      }
    },
  });
}
