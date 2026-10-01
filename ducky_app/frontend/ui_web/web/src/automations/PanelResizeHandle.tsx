import { useRef } from "react";

/** Drag (or arrow keys) to resize a side panel. ``edge`` is the panel side the handle sits
 *  on: a panel on the left grows when dragged right, one on the right when dragged left. */
export function PanelResizeHandle({ label, className, value, min, max, edge, onResize, onActive }: {
  label: string;
  className: string;
  value: number;
  min: number;
  max: number;
  edge: "right" | "left";
  onResize: (width: number) => void;
  /** True while a drag is under way (panels stop animating so they follow the pointer). */
  onActive?: (active: boolean) => void;
}) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const clamp = (width: number) => Math.round(Math.min(max, Math.max(min, width)));
  const end = () => { if (drag.current) { drag.current = null; onActive?.(false); } };
  return <div
    className={`aw-resize ${className}`}
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    aria-valuenow={value}
    aria-valuemin={min}
    aria-valuemax={max}
    tabIndex={0}
    title={label}
    onPointerDown={(event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      drag.current = { x: event.clientX, width: value };
      onActive?.(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={(event) => {
      if (!drag.current) return;
      const dx = event.clientX - drag.current.x;
      onResize(clamp(drag.current.width + (edge === "right" ? dx : -dx)));
    }}
    onPointerUp={end}
    onPointerCancel={end}
    onLostPointerCapture={end}
    onKeyDown={(event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const grow = (event.key === "ArrowRight") === (edge === "right");
      onResize(clamp(value + (grow ? 16 : -16)));
    }}
  />;
}
