import { useSyncExternalStore } from "react";

export const NARROW_LAYOUT_MQ = "(max-width: 720px)";

export function useNarrowLayout() {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(NARROW_LAYOUT_MQ);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(NARROW_LAYOUT_MQ).matches,
    () => false,
  );
}

/** A phone (narrow window or touch screen): focusing a text box there pops up the
 *  on-screen keyboard, so opening a chat or a picker must not focus one by itself. */
export function skipAutoFocus(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(NARROW_LAYOUT_MQ).matches || window.matchMedia("(pointer: coarse)").matches;
}
