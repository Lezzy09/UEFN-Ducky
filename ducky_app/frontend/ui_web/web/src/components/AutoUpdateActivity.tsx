import { useEffect } from "react";
import { isRemote } from "../hooks/usePanelApi";
import { startUpdateActivity, startUpdateReporting } from "../update/autoUpdate";

/** Background self-update: every window reports whether it's in use; the main one also
 *  keeps the update's row in background activity. Nothing on a phone or another PC. */
export function AutoUpdateActivity({ showActivity }: { showActivity: boolean }) {
  useEffect(() => (isRemote() ? undefined : startUpdateReporting()), []);
  useEffect(() => (isRemote() || !showActivity ? undefined : startUpdateActivity()), [showActivity]);
  return null;
}
