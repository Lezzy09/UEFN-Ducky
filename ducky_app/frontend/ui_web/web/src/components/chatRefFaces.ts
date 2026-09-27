import { useSyncExternalStore } from "react";

export interface ChatRefFace {
  duckyStyle?: string;
  iconUrl?: string;
}

const faces = new Map<string, ChatRefFace>();
const listeners = new Set<() => void>();
let version = 0;

export function noteChatRefFaces(rows: Array<{ href: string; duckyStyle?: string; iconUrl?: string }>): void {
  let changed = false;
  for (const row of rows) {
    const face: ChatRefFace = {};
    if (row.duckyStyle) face.duckyStyle = row.duckyStyle;
    if (row.iconUrl) face.iconUrl = row.iconUrl;
    if (!face.duckyStyle && !face.iconUrl) continue;
    const prev = faces.get(row.href);
    if (prev?.duckyStyle === face.duckyStyle && prev?.iconUrl === face.iconUrl) continue;
    faces.set(row.href, face);
    changed = true;
  }
  if (!changed) return;
  version += 1;
  listeners.forEach((listener) => listener());
}

export function chatRefFace(href: string): ChatRefFace | undefined {
  return faces.get(href);
}

export function useChatRefFace(href: string): ChatRefFace | undefined {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => faces.get(href),
    () => faces.get(href),
  );
}

export function useChatRefFaceVersion(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
    () => version,
  );
}
