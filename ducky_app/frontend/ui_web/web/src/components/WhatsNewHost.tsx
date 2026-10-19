import { useEffect, useState } from "react";
import { onApiReady } from "../hooks/onApiReady";
import { getApi, isRemote } from "../hooks/usePanelApi";
import { requestOpenSettings } from "../navigation/openSettingsTab";
import type { WhatsNewVersion } from "../types/panel";
import { WhatsNewModal } from "./WhatsNewModal";

type Shown = { current: string; versions: WhatsNewVersion[] };

const reopenListeners = new Set<() => void>();

/** Settings' "What's new" link: show the latest versions' changes again. */
export function openWhatsNew(): void {
  for (const fn of [...reopenListeners]) fn();
}

/** Run ``fn`` once this window is on screen and focused (after a live swap it may be hidden). */
function whenFocused(fn: () => void): () => void {
  if (document.visibilityState === "visible" && document.hasFocus()) {
    fn();
    return () => {};
  }
  const onFocus = () => {
    if (document.visibilityState !== "visible") return;
    window.removeEventListener("focus", onFocus);
    fn();
  };
  window.addEventListener("focus", onFocus);
  return () => window.removeEventListener("focus", onFocus);
}

/** Opens What's new once after an update, and again when Settings asks. */
export function WhatsNewHost() {
  const [shown, setShown] = useState<Shown | null>(null);

  useEffect(() => {
    if (isRemote()) return;
    let stopWaiting = () => {};
    let cancelled = false;
    const stopReady = onApiReady(() => {
      const api = getApi();
      if (!api || typeof api.get_whats_new !== "function") return;
      void api
        .get_whats_new()
        .then((status) => {
          if (cancelled || !status?.show || !status.versions?.length) return;
          stopWaiting = whenFocused(() => setShown({ current: status.current, versions: status.versions }));
        })
        .catch(() => {});
    });
    return () => {
      cancelled = true;
      stopReady();
      stopWaiting();
    };
  }, []);

  useEffect(() => {
    const reopen = () => {
      const api = getApi();
      if (!api || typeof api.get_whats_new !== "function") return;
      void api
        .get_whats_new()
        .then((status) => {
          const versions = status?.versions?.length ? status.versions : status?.recent ?? [];
          if (versions.length) setShown({ current: status.current, versions });
        })
        .catch(() => {});
    };
    reopenListeners.add(reopen);
    return () => {
      reopenListeners.delete(reopen);
    };
  }, []);

  if (!shown) return null;

  const close = (dontShowAgain: boolean) => {
    const api = getApi();
    if (api && typeof api.mark_whats_new_seen === "function") {
      void api.mark_whats_new_seen(shown.current, dontShowAgain).catch(() => {});
    }
    setShown(null);
  };

  return (
    <WhatsNewModal
      open
      current={shown.current}
      versions={shown.versions}
      onClose={close}
      onAllNotes={() => {
        close(false);
        requestOpenSettings("General");
      }}
    />
  );
}
