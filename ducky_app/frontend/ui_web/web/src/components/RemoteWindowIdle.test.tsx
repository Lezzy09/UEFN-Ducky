// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { IDLE_PAUSE_MS, useIdlePause } from "./RemoteWindowView";

afterEach(() => vi.useRealTimers());

it("pauses a stream nobody touched for five minutes, and a touch keeps it going", () => {
  vi.useFakeTimers();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const ref = { current: el };
  const { result } = renderHook(() => useIdlePause(ref, true));
  act(() => void vi.advanceTimersByTime(IDLE_PAUSE_MS - 30_000));
  act(() => void el.dispatchEvent(new Event("pointerdown")));
  act(() => void vi.advanceTimersByTime(IDLE_PAUSE_MS - 30_000));
  expect(result.current.idle).toBe(false);
  act(() => void vi.advanceTimersByTime(60_000));
  expect(result.current.idle).toBe(true);
  act(() => result.current.resume());
  expect(result.current.idle).toBe(false);
});
