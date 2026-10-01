/**
 * The Show me highlight: everything is dimmed and can't be clicked except the target,
 * which gets a ring; a popup above it explains it. Only the popup's close button ends it.
 *
 * Measuring runs in a requestAnimationFrame loop that writes CSS variables and data
 * attributes straight onto the elements — never React state per frame (React #185).
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MarkdownContent } from "../components/rich-content/MarkdownContent";
import { Icons } from "../icons/Icons";
import { clipOutside, holeFor, modeFor, offscreenSide, placeCard, unionBox } from "../ui-targets/geometry";
import { resolveTarget, revealTarget, type TargetSpec } from "../ui-targets/resolve";
import { targetRef } from "../ui-targets/registry";
import { backShowMe, closeShowMe, getShowMeState, nextShowMe, subscribeShowMe, targetsOf } from "./ShowMeService";
import "./showme.css";

const POPUP_W = 360;
const RESOLVE_EVERY_MS = 400;

export function ShowMeLayer() {
  const [, setEpoch] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => subscribeShowMe(() => setEpoch((n) => n + 1)), []);

  const { request, phase, key, index, total } = getShowMeState();
  const active = !!request;
  const many = total > 1;
  const last = index >= total - 1;

  // Follow the target(s): re-find them now and then, measure every frame.
  useEffect(() => {
    if (!request || phase !== "shown") return;
    const targets = targetsOf(request);
    let els: Array<HTMLElement | null> = targets.map((t) => resolveTarget(t));
    let lastResolve = Date.now();
    let raf = 0;
    const tick = () => {
      const root = rootRef.current;
      const popup = popupRef.current;
      if (root && popup) {
        if (Date.now() - lastResolve > RESOLVE_EVERY_MS || els.some((el) => el && !el.isConnected)) {
          els = targets.map((t) => resolveTarget(t));
          lastResolve = Date.now();
        }
        const box = unionBox(els.filter((el): el is HTMLElement => !!el).map((el) => el.getBoundingClientRect()));
        const blocker = root.querySelector<HTMLElement>(".showme-blocker");
        if (box) {
          const hole = holeFor(box, targets.length === 1 ? modeFor(box) : "rect");
          root.style.setProperty("--sm-x", `${hole.left}px`);
          root.style.setProperty("--sm-y", `${hole.top}px`);
          root.style.setProperty("--sm-w", `${hole.width}px`);
          root.style.setProperty("--sm-h", `${hole.height}px`);
          root.style.setProperty("--sm-r", hole.radius);
          if (blocker) blocker.style.clipPath = clipOutside(hole);
          const away = offscreenSide(hole);
          root.dataset.away = away;
          const place = placeCard(away ? null : hole, POPUP_W, popup.offsetHeight || 160, "above");
          root.style.setProperty("--sm-pop-x", `${place.x}px`);
          root.style.setProperty("--sm-pop-y", `${place.y}px`);
          root.style.setProperty("--sm-arrow-x", `${place.arrowX}px`);
          popup.dataset.side = place.side;
          root.dataset.hole = "1";
        } else {
          root.dataset.hole = "";
          if (blocker) blocker.style.clipPath = "none";
          const place = placeCard(null, POPUP_W, popup.offsetHeight || 160);
          root.style.setProperty("--sm-pop-x", `${place.x}px`);
          root.style.setProperty("--sm-pop-y", `${place.y}px`);
          popup.dataset.side = "center";
        }
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [request, phase, key]);

  // Not shown yet (going there) or can't be found: centered popup, nothing clickable.
  useEffect(() => {
    if (!request || phase === "shown") return;
    const root = rootRef.current;
    const popup = popupRef.current;
    if (!root || !popup) return;
    root.dataset.hole = "";
    root.dataset.away = "";
    const blocker = root.querySelector<HTMLElement>(".showme-blocker");
    if (blocker) blocker.style.clipPath = "none";
    const place = placeCard(null, POPUP_W, popup.offsetHeight || 160);
    root.style.setProperty("--sm-pop-x", `${place.x}px`);
    root.style.setProperty("--sm-pop-y", `${place.y}px`);
    popup.dataset.side = "center";
  }, [request, phase, key]);

  // A "click" step moves on when the user clicks the highlighted thing (after it reacts).
  useEffect(() => {
    if (!request?.click || phase !== "shown" || last) return;
    const els = targetsOf(request).map((t) => resolveTarget(t)).filter((el): el is HTMLElement => !!el);
    if (!els.length) return;
    let timer = 0;
    const onClick = () => { timer = window.setTimeout(() => nextShowMe(), 350); };
    for (const el of els) el.addEventListener("click", onClick, { capture: true });
    return () => {
      window.clearTimeout(timer);
      for (const el of els) el.removeEventListener("click", onClick, { capture: true });
    };
  }, [request, phase, key, last]);

  // Focus moves to the close button; back where it was after closing.
  useEffect(() => {
    if (!active) return;
    if (!returnFocus.current) returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
  }, [active, key]);

  const close = () => {
    const back = returnFocus.current;
    returnFocus.current = null;
    closeShowMe();
    try {
      back?.focus({ preventScroll: true });
    } catch {
      /* gone */
    }
  };

  if (!request) return null;
  const first = targetsOf(request)[0] as TargetSpec | undefined;
  const titleId = `showme-title-${key}`;

  return createPortal(
    <div ref={rootRef} className="showme-overlay" data-phase={phase} data-hole="" data-away="">
      {/* Swallows every click outside the hole: only the close button ends Show me. */}
      <div
        className="showme-blocker"
        aria-hidden
        onPointerDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
        onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); }}
      />
      <div className="showme-hole" aria-hidden />
      <div className="showme-ring" aria-hidden />
      <div ref={(el) => { popupRef.current = el; targetRef("showme.popup", { label: "Show me popup" })(el); }} className="showme-popup" role="dialog" aria-modal="false" aria-labelledby={titleId} data-side="center">
        <div className="showme-popup-head">
          <span className="showme-popup-icon" aria-hidden><Icons.Sparkles /></span>
          <h3 id={titleId} className="showme-popup-title">{request.title}</h3>
          <button ref={(el) => { closeRef.current = el; targetRef("showme.close", { label: "Close Show me" })(el); }} type="button" className="showme-close" aria-label="Close" title="Close" onClick={close}>
            <Icons.Close />
          </button>
        </div>
        <div className="showme-popup-body" aria-live="polite">
          {phase === "going" ? <p className="showme-going">Taking you there…</p> : null}
          {request.body ? <MarkdownContent text={request.body} /> : null}
          {phase === "missing" ? <p className="showme-missing">Can't find this on screen right now. It may be in a view that's closed.</p> : null}
        </div>
        {first ? (
          <button type="button" className="showme-back" onClick={() => void revealTarget(first)}>
            Bring it back into view
          </button>
        ) : null}
        {many ? (
          <div className="showme-steps">
            <span className="showme-steps-count">{index + 1} / {total}</span>
            {request.click && !last && phase === "shown" ? <span className="showme-steps-hint">Click the highlight to go on</span> : null}
            <span className="showme-steps-actions">
              {/* Off while a step is on its way, so a double-click on Next doesn't skip or close. */}
              {index > 0 ? <button type="button" className="showme-step-btn" disabled={phase === "going"} onClick={backShowMe}>Back</button> : null}
              {last
                ? <button key="close" type="button" className="showme-step-btn showme-step-btn--primary" disabled={phase === "going"} onClick={close}>Close</button>
                : <button key="next" type="button" className="showme-step-btn showme-step-btn--primary" disabled={phase === "going"} onClick={nextShowMe}>Next</button>}
            </span>
          </div>
        ) : null}
        <span className="showme-arrow" aria-hidden />
      </div>
    </div>,
    document.body,
  );
}
