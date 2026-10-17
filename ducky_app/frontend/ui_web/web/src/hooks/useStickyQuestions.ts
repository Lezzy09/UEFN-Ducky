import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "uefn-chat-sticky-questions";
const CHANGE_EVENT = "uefn-chat-sticky-questions-changed";

/** Off by default: each question stays where it was asked instead of pinning to the top. */
export function readStickyQuestions(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function persistStickyQuestions(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  } catch {
    // ignore storage errors
  }
  window.dispatchEvent(new CustomEvent<boolean>(CHANGE_EVENT, { detail: on }));
}

export function useStickyQuestions() {
  const [sticky, setStickyState] = useState(readStickyQuestions);

  useEffect(() => {
    const sync = (event: Event) => {
      setStickyState(
        event instanceof CustomEvent && typeof event.detail === "boolean" ? event.detail : readStickyQuestions(),
      );
    };
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const setSticky = useCallback((on: boolean) => {
    persistStickyQuestions(on);
    setStickyState(on);
  }, []);

  return { sticky, setSticky };
}
