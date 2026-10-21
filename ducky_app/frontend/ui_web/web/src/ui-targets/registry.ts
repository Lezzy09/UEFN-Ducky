/**
 * Registry of spotlightable panel controls.
 *
 * Components tag a DOM node with `useUiTarget("<semantic-id>")`; the guided-UI
 * MCP tools (ducky_ui_list_targets / ducky_walkthrough_run) look controls up by
 * that id. Ids are stable and semantic (`settings.mcp.apply`), never DOM
 * indexes, so a tool can reference a control without knowing the tree shape.
 */
import { useCallback, useRef } from "react";

export type UiTargetKind =
  | "tab"
  | "button"
  | "input"
  | "toggle"
  | "dropdown"
  | "chat"
  | "settings_field"
  | "plugin_row"
  | "skill_row";

export interface UiTargetMeta {
  label?: string;
  route?: string;
  kind?: UiTargetKind;
}

interface Entry {
  el: HTMLElement;
  meta: UiTargetMeta;
}

// Several components can carry one id (the docked Duckies list and a hidden copy of it), so an
// id keeps every element that tagged it. One leaving must not take the id from the others.
const registry = new Map<string, Entry[]>();

export function registerTarget(id: string, el: HTMLElement, meta: UiTargetMeta = {}): void {
  registry.set(id, [...(registry.get(id) || []).filter((e) => e.el !== el), { el, meta }]);
}

function keepOnly(id: string, keep: (e: Entry) => boolean): void {
  const left = (registry.get(id) || []).filter(keep);
  if (left.length) registry.set(id, left);
  else registry.delete(id);
}

/** Forget `el` for `id`, or the whole id when no element is named. */
export function unregisterTarget(id: string, el?: HTMLElement): void {
  if (el) keepOnly(id, (e) => e.el !== el);
  else registry.delete(id);
}

/** The element an id means now: the newest visible one still on the page, else the newest on it. */
function entryFor(id: string): Entry | null {
  const live = (registry.get(id) || []).filter((e) => e.el.isConnected);
  for (let i = live.length - 1; i >= 0; i--) if (isVisible(live[i]!.el)) return live[i]!;
  return live[live.length - 1] ?? null;
}

export function getTargetElement(id: string): HTMLElement | null {
  return entryFor(id)?.el ?? null;
}

function isVisible(el: HTMLElement): boolean {
  if (el.closest("[inert]")) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
  return true;
}

function isEnabled(el: HTMLElement): boolean {
  if ((el as HTMLButtonElement).disabled) return false;
  return el.getAttribute("aria-disabled") !== "true";
}

function labelFor(id: string, entry: Entry): string {
  if (entry.meta.label) return entry.meta.label;
  const text = (entry.el.getAttribute("aria-label") || entry.el.textContent || "").trim();
  if (text) return text.length > 60 ? `${text.slice(0, 57)}…` : text;
  return id;
}

export interface UiTargetInfo {
  id: string;
  label: string;
  route: string;
  rect: { x: number; y: number; w: number; h: number };
  visible: boolean;
  enabled: boolean;
  kind: UiTargetKind | "button";
}

/** Snapshot every registered target; `routeHint` filters by declared route prefix. */
export function listTargets(routeHint = ""): UiTargetInfo[] {
  const hint = routeHint.trim();
  const out: UiTargetInfo[] = [];
  for (const id of registry.keys()) {
    const entry = entryFor(id);
    if (!entry) continue;
    const route = entry.meta.route ?? "";
    if (hint && route && !route.startsWith(hint) && !id.startsWith(hint)) continue;
    const rect = entry.el.getBoundingClientRect();
    out.push({
      id,
      label: labelFor(id, entry),
      route,
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
      visible: isVisible(entry.el),
      enabled: isEnabled(entry.el),
      kind: entry.meta.kind ?? "button",
    });
  }
  out.sort((a, b) => a.id.localeCompare(b.id));
  return out;
}

/**
 * Attach a stable spotlight id to a DOM node. Returns a ref callback:
 * `<button ref={useUiTarget("settings.mcp.apply", { kind: "button" })}>`.
 */
/** Combine an object ref with a callback ref (ui-target + dropdown anchor). */
export function useMergedRef<T extends HTMLElement>(
  obj: { current: T | null },
  cb: (el: T | null) => void,
) {
  return useCallback(
    (el: T | null) => {
      (obj as { current: T | null }).current = el;
      cb(el);
    },
    [obj, cb],
  );
}

export function useUiTarget(id: string, meta: UiTargetMeta = {}) {
  const metaRef = useRef(meta);
  metaRef.current = meta;
  const elRef = useRef<HTMLElement | null>(null);
  return useCallback(
    (el: HTMLElement | null) => {
      if (!id) return;
      if (el) {
        elRef.current = el;
        registerTarget(id, el, metaRef.current);
      } else if (elRef.current) {
        unregisterTarget(id, elRef.current);
        elRef.current = null;
      }
    },
    [id],
  );
}

const refCache = new Map<string, (el: HTMLElement | null) => void>();
const metaCache = new Map<string, UiTargetMeta>();

/**
 * Non-hook variant of {@link useUiTarget} for use inside `.map()` where hooks
 * can't run. Returns a per-id stable ref callback (no re-register churn) and
 * refreshes the stored metadata on each render.
 */
export function targetRef(id: string, meta: UiTargetMeta = {}) {
  metaCache.set(id, meta);
  let fn = refCache.get(id);
  if (!fn) {
    fn = (el: HTMLElement | null) => {
      if (el) registerTarget(id, el, metaCache.get(id) ?? {});
      // One callback serves every copy, so React's null doesn't say which left: drop the ones
      // off the page, now and once the commit has removed the old node.
      else {
        const prune = () => keepOnly(id, (e) => e.el.isConnected);
        prune();
        queueMicrotask(prune);
      }
    };
    refCache.set(id, fn);
  }
  return fn;
}

/** Slug for a settings tab label, e.g. "Skills & MCP" → "skills-mcp". */
export function settingsTabTargetId(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/&/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join("-");
  return `settings.tab.${slug}`;
}
