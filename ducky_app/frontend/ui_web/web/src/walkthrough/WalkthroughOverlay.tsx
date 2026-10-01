/**
 * Product walkthrough overlay: dim hole + coachmark (Skip / Back / Next).
 * `require_click` steps punch a click-through hole; other steps block the page.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { clipOutside, holeFor, placeCard } from "../ui-targets/geometry";
import { resolveTarget, revealTarget, type TargetSpec } from "../ui-targets/resolve";
import { MarkdownContent } from "../components/rich-content/MarkdownContent";
import {
  getActiveStep,
  getActiveSteps,
  getWalkthroughState,
  isStepEntered,
  nextStep,
  prevStep,
  skipTour,
  subscribeWalkthrough,
} from "./WalkthroughService";
import "./walkthrough.css";

const TIP_W = 340;

function placeTooltip(hole: DOMRect | null, tipH: number): { x: number; y: number } {
  return placeCard(hole, TIP_W, tipH, "below");
}

export function WalkthroughOverlay() {
  const [epoch, setEpoch] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);
  // tip height is ref-only — setState here re-rendered every measure and could
  // oscillate with layout (React #185). rAF already reads tipHRef.
  const tipHRef = useRef(160);
  const [missing, setMissing] = useState(false);
  const missingRef = useRef(false);

  useEffect(() => {
    return subscribeWalkthrough(() => setEpoch((n) => n + 1));
  }, []);

  const state = getWalkthroughState();
  const step = getActiveStep();
  const steps = getActiveSteps();
  const active = state.active && !!step;
  // A role/name spec when the step has one, else its id.
  const stepTarget: TargetSpec | undefined = step?.spec ?? step?.target;
  const stepAdvance = step?.advance;
  const stepMode = step?.mode;

  useEffect(() => {
    if (!active || !stepTarget) return;
    let raf = 0;
    const tick = () => {
      const el = resolveTarget(stepTarget);
      const root = rootRef.current;
      if (root) {
        if (el) {
          const rect = el.getBoundingClientRect();
          const hole = holeFor(rect, stepMode === "circle" ? "circle" : "rect");
          const { left, top, width: rw, height: rh } = hole;
          root.style.setProperty("--wt-x", `${left}px`);
          root.style.setProperty("--wt-y", `${top}px`);
          root.style.setProperty("--wt-w", `${rw}px`);
          root.style.setProperty("--wt-h", `${rh}px`);
          root.style.setProperty("--wt-r", hole.radius);
          const tip = placeTooltip(
            new DOMRect(left, top, rw, rh),
            tipHRef.current,
          );
          root.style.setProperty("--wt-tip-x", `${tip.x}px`);
          root.style.setProperty("--wt-tip-y", `${tip.y}px`);
          if (missingRef.current) {
            missingRef.current = false;
            setMissing(false);
          }

          // Punch click-through hole for require_click via clip-path on blocker.
          const blocker = root.querySelector(".walkthrough-blocker") as HTMLElement | null;
          if (blocker) {
            if (stepAdvance === "require_click") {
              blocker.style.clipPath = clipOutside(hole);
            } else {
              blocker.style.clipPath = "none";
            }
          }
        } else {
          if (!missingRef.current) {
            missingRef.current = true;
            setMissing(true);
          }
          const tip = placeTooltip(null, tipHRef.current);
          root.style.setProperty("--wt-x", `0px`);
          root.style.setProperty("--wt-y", `0px`);
          root.style.setProperty("--wt-w", `0px`);
          root.style.setProperty("--wt-h", `0px`);
          root.style.setProperty("--wt-tip-x", `${tip.x}px`);
          root.style.setProperty("--wt-tip-y", `${tip.y}px`);
          const blocker = root.querySelector(".walkthrough-blocker") as HTMLElement | null;
          if (blocker) blocker.style.clipPath = "none";
        }
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [active, stepTarget, stepAdvance, stepMode, epoch]);

  // Bring the target into view once the step's own setup (open a view, select a node) is
  // done — revealing earlier lost to the view restoring its own camera or scroll.
  const entered = active && isStepEntered();
  useEffect(() => {
    if (!active || !stepTarget || !entered) return;
    if (!resolveTarget(stepTarget)) return;
    void revealTarget(stepTarget);
  }, [active, stepTarget, state.stepIndex, entered]);

  useEffect(() => {
    if (!active || !stepTarget || stepAdvance !== "require_click") return;
    const el = resolveTarget(stepTarget);
    if (!el) return;
    const onClick = () => {
      void nextStep();
    };
    el.addEventListener("click", onClick, { capture: true });
    return () => el.removeEventListener("click", onClick, { capture: true });
  }, [active, stepTarget, stepAdvance, epoch]);

  useEffect(() => {
    if (!tipRef.current) return;
    const h = Math.round(tipRef.current.getBoundingClientRect().height);
    if (h > 0) tipHRef.current = h;
  }, [step?.title, step?.body, state.stepIndex, active]);

  if (!active || !step) return null;

  const isLast = state.stepIndex >= steps.length - 1;
  const requireClick = step.advance === "require_click";

  return createPortal(
    <div ref={rootRef} className="walkthrough-overlay" role="dialog" aria-modal="true" aria-label={step.title}>
      <div className="walkthrough-blocker" aria-hidden />
      <div className="walkthrough-hole" aria-hidden />
      <div className="walkthrough-ring" aria-hidden />
      <div ref={tipRef} className="walkthrough-tooltip">
        <button type="button" className="walkthrough-tooltip-skip" onClick={() => void skipTour()}>
          Skip
        </button>
        <h3 className="walkthrough-tooltip-title">{step.title}</h3>
        <div className="walkthrough-tooltip-body"><MarkdownContent text={step.body} /></div>
        {missing ? (
          <p className="walkthrough-missing">Target not visible yet — open that area or press Next.</p>
        ) : null}
        <div className="walkthrough-tooltip-footer">
          <span className="walkthrough-tooltip-count">
            {state.stepIndex + 1} / {steps.length}
          </span>
          <div className="walkthrough-tooltip-actions">
            {state.stepIndex > 0 ? (
              <button type="button" className="walkthrough-btn" onClick={() => void prevStep()}>
                Back
              </button>
            ) : null}
            {requireClick ? (
              <span className="walkthrough-tooltip-count">Click the highlight</span>
            ) : null}
            {requireClick ? (
              <button
                type="button"
                className="walkthrough-btn"
                onClick={() => void nextStep()}
              >
                Skip
              </button>
            ) : (
              <button
                type="button"
                className="walkthrough-btn walkthrough-btn-primary"
                onClick={() => void nextStep()}
              >
                {isLast ? "Got it" : "Next"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
