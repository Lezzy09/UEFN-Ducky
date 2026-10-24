// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { hoverCardsOff, useEditorTabHoverCard } from "./useEditorTabHoverCard";

it("a tap never opens a hover card (a phone has no mouseleave to close it)", () => {
  vi.useFakeTimers();
  const { result } = renderHook(() => useEditorTabHoverCard());
  // A mouse hover still opens it.
  act(() => result.current.scheduleShow());
  act(() => { vi.advanceTimersByTime(300); });
  expect(result.current.open).toBe(true);
  act(() => result.current.scheduleHide());
  act(() => { vi.advanceTimersByTime(300); });

  // A touch: the tap's emulated mouseenter is ignored.
  window.dispatchEvent(Object.assign(new Event("pointerdown"), { pointerType: "touch" }));
  expect(hoverCardsOff()).toBe(true);
  act(() => result.current.scheduleShow());
  act(() => { vi.advanceTimersByTime(300); });
  expect(result.current.open).toBe(false);
  vi.useRealTimers();
});
