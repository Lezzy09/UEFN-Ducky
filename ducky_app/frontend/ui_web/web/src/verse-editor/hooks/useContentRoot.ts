import { useSyncExternalStore } from "react";

import { contentRootPath, subscribeContentRoot } from "../utils/isVerseFile";

/** The active content root (`Content` or `.`); re-renders when project info sets it, so
 * locks computed with isPanelReadOnlyFile follow the real project kind. */
export function useContentRoot(): string {
  return useSyncExternalStore(subscribeContentRoot, contentRootPath, contentRootPath);
}
