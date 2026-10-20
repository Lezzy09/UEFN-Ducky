import { useEffect } from "react";
import { onApiReady } from "../hooks/onApiReady";
import { isRemote } from "../hooks/usePanelApi";
import { startUpdateActivity, startUpdateReporting } from "../update/autoUpdate";

/** Run ``start`` once the panel API is ready (the first report must not wait a whole tick). */
function whenApiReady(start: () => () => void): () => void {
  let stop: (() => void) | null = null;
  let cancelled = false;
  const off = onApiReady(() => {
    if (!cancelled && !stop) stop = start();
  });
  return () => {
    cancelled = true;
    off();
    stop?.();
  };
}

/** Background self-update: every window reports whether it's in use; the main one also
 *  keeps the update's row in background activity. Nothing on a phone or another PC. */
export function AutoUpdateActivity({ showActivity }: { showActivity: boolean }) {
  useEffect(() => (isRemote() ? undefined : whenApiReady(startUpdateReporting)), []);
  useEffect(() => (isRemote() || !showActivity ? undefined : whenApiReady(startUpdateActivity)), [showActivity]);
  return null;
}
