import { useCallback, useEffect, useRef, useState } from "react";

import {
  computeEditorTabHoverCardPosition,
  EDITOR_TAB_HOVER_CARD_EST_HEIGHT,
  EDITOR_TAB_HOVER_CARD_WIDTH,
  type EditorTabHoverCardPlacement,
} from "./editorTabHoverCardPosition";

export { EDITOR_TAB_HOVER_CARD_WIDTH };
export type { EditorTabHoverCardPlacement };

const SHOW_DELAY_MS = 180;
const HIDE_DELAY_MS = 120;
/** A tap also sends mouseenter and focus; a card opened by one has no mouseleave to close it. */
const TOUCH_WINDOW_MS = 1000;

let lastTouchAt = 0;
let touchWatch = false;

function watchTouches(): void {
  if (touchWatch || typeof window === "undefined") return;
  touchWatch = true;
  window.addEventListener(
    "pointerdown",
    (e) => {
      if (e.pointerType === "touch" || e.pointerType === "pen") lastTouchAt = Date.now();
    },
    { capture: true, passive: true },
  );
}

/** Phones and tablets never show hover cards: there is no hover, only a tap that opens the row. */
export function hoverCardsOff(now = Date.now()): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia?.("(hover: none)").matches) return true;
  return now - lastTouchAt < TOUCH_WINDOW_MS;
}

export function useEditorTabHoverCard(
  disabled = false,
  placement: EditorTabHoverCardPlacement = "below",
  cardHeight = EDITOR_TAB_HOVER_CARD_EST_HEIGHT,
) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const showTimerRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);

  const clearTimers = () => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  };

  const updatePosition = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    // Prefer the visible row box — the anchor span can disagree under nested scroll/split panes.
    const target =
      (el.querySelector(".sidebar-tree-row") as HTMLElement | null) ?? el;
    setPos(
      computeEditorTabHoverCardPosition(
        target.getBoundingClientRect(),
        placement,
        { width: window.innerWidth, height: window.innerHeight },
        cardHeight,
      ),
    );
  }, [placement, cardHeight]);

  const showCard = useCallback(() => {
    if (hoverCardsOff()) return;
    updatePosition();
    setOpen(true);
  }, [updatePosition]);

  useEffect(() => watchTouches(), []);

  const scheduleShow = useCallback(() => {
    if (disabled || hoverCardsOff()) return;
    clearTimers();
    showTimerRef.current = window.setTimeout(showCard, SHOW_DELAY_MS);
  }, [disabled, showCard]);

  const scheduleHide = useCallback(() => {
    clearTimers();
    hideTimerRef.current = window.setTimeout(() => setOpen(false), HIDE_DELAY_MS);
  }, []);

  const cancelHide = useCallback(() => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => clearTimers(), []);

  useEffect(() => {
    if (!disabled) return;
    clearTimers();
    setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => setOpen(false);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  return {
    anchorRef,
    open,
    pos,
    scheduleShow,
    scheduleHide,
    cancelHide,
  };
}
