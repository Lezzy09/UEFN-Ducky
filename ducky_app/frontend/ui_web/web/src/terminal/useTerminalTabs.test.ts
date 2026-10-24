// @vitest-environment jsdom
import { act, cleanup, render, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { EditorTab } from "../types/panel";

const api = vi.hoisted(() => ({ terminal_list: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
const bus = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("../hooks/useAgentEventBus", () => ({
  subscribeAgentEvents: (handler: (event: Record<string, unknown>) => void) => {
    bus.handlers.add(handler);
    return () => bus.handlers.delete(handler);
  },
}));
const push = (event: Record<string, unknown>) => { for (const h of [...bus.handlers]) h(event); };
vi.mock("../contexts/TerminalsSettingsContext", () => ({ getTerminalsEnabled: () => true }));

import { useTerminalTabs } from "./useTerminalTabs";

const editor = {
  openTab: vi.fn(),
  closeTabInLayout: vi.fn(),
  openTabsRef: { current: [] as EditorTab[] },
  remapTabId: vi.fn(),
  setOpenTabs: vi.fn(),
};

const session = (id: string) => ({ session_id: id, shell: "pwsh", cwd: "C:/work", title: `Shell ${id}`, ws_url: `ws://127.0.0.1:1/${id}` });

beforeEach(() => {
  vi.useFakeTimers();
  api.terminal_list.mockResolvedValue({ sessions: [session("a"), session("b")] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  api.terminal_list.mockReset();
  editor.openTab.mockReset();
  editor.openTabsRef.current = [];
});

it("lists an agent's terminal in the header instead of opening it over the chat", async () => {
  api.terminal_list.mockResolvedValue({ sessions: [] });
  const { result } = renderHook(() => useTerminalTabs(editor));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  act(() => push({ type: "terminal_open", ...session("agent"), activate: false }));
  expect(editor.openTab).not.toHaveBeenCalled();
  expect(result.current.parkedTabs.map((t) => t.terminalSessionId)).toEqual(["agent"]);

  // Already open as a tab (an agent reused it): left as it is, never listed twice.
  editor.openTabsRef.current = [{ id: "terminal:open", kind: "terminal", name: "open", terminalSessionId: "open" }];
  act(() => push({ type: "terminal_open", ...session("open"), activate: false }));
  expect(editor.openTab).not.toHaveBeenCalled();
  expect(result.current.parkedTabs.map((t) => t.terminalSessionId)).toEqual(["agent"]);
});

it("does not re-render the chat view when the parked shells are unchanged", async () => {
  // The hook lives in the chat view; count renders of what the view draws below it.
  let childRenders = 0;
  let parked: EditorTab[] = [];
  function Child({ tabs }: { tabs: EditorTab[] }) {
    childRenders += 1;
    parked = tabs;
    return null;
  }
  function View() {
    const { parkedTabs } = useTerminalTabs(editor);
    return createElement(Child, { tabs: parkedTabs });
  }
  render(createElement(View));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(parked.map((t) => t.terminalSessionId)).toEqual(["a", "b"]);
  const first = parked;
  const rendersAfterFirst = childRenders;

  for (let i = 0; i < 5; i++) {
    act(() => push({ type: "terminal_busy", session_id: "a", busy: i % 2 === 0 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  }

  expect(api.terminal_list.mock.calls.length).toBe(6);
  expect(childRenders).toBe(rendersAfterFirst);
  expect(parked).toBe(first);
});

it("still picks up a shell that started or ended elsewhere", async () => {
  const { result } = renderHook(() => useTerminalTabs(editor));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });

  api.terminal_list.mockResolvedValue({ sessions: [session("b"), session("c")] });
  act(() => push({ type: "terminal_close", session_id: "a" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(result.current.parkedTabs.map((t) => t.terminalSessionId).sort()).toEqual(["b", "c"]);

  api.terminal_list.mockResolvedValue({ sessions: [session("b"), { ...session("c"), title: "Renamed" }] });
  act(() => push({ type: "terminal_busy", session_id: "c", busy: true }));
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(result.current.parkedTabs.find((t) => t.terminalSessionId === "c")?.name).toContain("Renamed");
});

it("lists shells once on mount, never while idle, once per burst of pushes", async () => {
  renderHook(() => useTerminalTabs(editor));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(api.terminal_list).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000); });
  expect(api.terminal_list).toHaveBeenCalledTimes(1);

  act(() => {
    push({ type: "terminal_open", ...session("c"), activate: false });
    push({ type: "terminal_busy", session_id: "c", busy: true });
    push({ type: "text_delta", conv_id: "x" });
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(api.terminal_list).toHaveBeenCalledTimes(2);
});
