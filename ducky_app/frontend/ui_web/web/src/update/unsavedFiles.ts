/** Unsaved files across this window's editors, so the auto-update never switches over them. */

const counts = new Map<symbol, number>();

/** An editor's unsaved-file count; call with 0 (or the returned cleanup) when it goes away. */
export function publishUnsavedFiles(owner: symbol, count: number): () => void {
  if (count > 0) counts.set(owner, count);
  else counts.delete(owner);
  return () => {
    counts.delete(owner);
  };
}

export function unsavedFileCount(): number {
  let total = 0;
  for (const n of counts.values()) total += n;
  return total;
}
