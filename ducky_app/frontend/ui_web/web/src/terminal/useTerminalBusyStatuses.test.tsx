// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppHeaderActionsProvider, useAppHeaderActions } from "../contexts/AppHeaderActionsContext";
import type { EditorLayoutState, EditorTab } from "../types/panel";

const api = vi.hoisted(() => ({ terminal_busy: vi.fn(), terminal_busy_many: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
const bus = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("../hooks/useAgentEventBus", () => ({
  subscribeAgentEvents: (handler: (event: Record<string, unknown>) => void) => {
    bus.handlers.add(handler);
    return () => bus.handlers.delete(handler);
  },
}));
const push = (event: Record<string, unknown>) => { for (const h of [...bus.handlers]) h(event); };
vi.mock("../contexts/TerminalsSettingsContext", () => ({ useTerminalsSettings: () => ({ enabled: true }) }));

import { TerminalHeaderBridge } from "../components/TerminalHeaderBridge";
import { useTerminalBusyStatuses } from "./useTerminalBusyStatuses";

let runningIds = new Set(["s2"]);
const running = (id: string) => runningIds.has(id);
const terminal = (n: number): EditorTab => ({ id: `t${n}`, kind: "terminal", name: `T${n}`, terminalSessionId: `s${n}` });
const open = [terminal(1), terminal(2), terminal(3)];
const parked = [terminal(4)];
const layout: EditorLayoutState = {
  root: { type: "group", groupId: "main" },
  groups: { main: { id: "main", tabIds: open.map((t) => t.id), activeTabId: "t1" } },
  focusedGroupId: "main",
};

let headerRenders = 0;
let stripRenders = 0;

function Header() {
  const { terminal: menu } = useAppHeaderActions();
  headerRenders += 1;
  return <span data-testid="running">{menu?.terminals.filter((t) => t.running).map((t) => t.sessionId).join(",")}</span>;
}

/** What each editor group's tab strip does with its terminal tabs. */
function TabStrip({ ids }: { ids: string[] }) {
  useTerminalBusyStatuses(ids);
  stripRenders += 1;
  return null;
}

const noop = () => {};

function App() {
  return (
    <AppHeaderActionsProvider>
      <Header />
      <TerminalHeaderBridge projectPath="C:/Project" openTabs={open} parkedTabs={parked} layout={layout}
        defaultTerminalShell="bash" setDefaultTerminalShell={noop} onNewTerminal={noop} onCloseTerminal={noop}
        activateTabInGroup={noop} setFocusedGroup={noop} />
      <TabStrip ids={["s1", "s2", "s3"]} />
    </AppHeaderActionsProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  runningIds = new Set(["s2"]);
  headerRenders = 0;
  stripRenders = 0;
  api.terminal_busy.mockImplementation(async (id: string) => ({ ok: true, busy: false, running: running(id) }));
  api.terminal_busy_many.mockImplementation(async (ids: string[]) => ({
    ok: true, states: Object.fromEntries(ids.map((id) => [id, { ok: true, busy: false, running: running(id) }])),
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

const calls = () => api.terminal_busy.mock.calls.length + api.terminal_busy_many.mock.calls.length;
const askedFor = (id: string) =>
  api.terminal_busy.mock.calls.filter(([sid]) => sid === id).length
  + api.terminal_busy_many.mock.calls.filter(([ids]) => (ids as string[]).includes(id)).length;

it("asks once on mount, then nothing for 10 idle minutes and no re-renders", async () => {
  const view = render(<App />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(view.getByTestId("running").textContent).toBe("s2");
  const settled = calls();
  expect(settled).toBeLessThanOrEqual(2);
  expect(askedFor("s4")).toBeGreaterThanOrEqual(1);
  const header = headerRenders;
  const strip = stripRenders;

  await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000); });

  expect(calls()).toBe(settled);
  expect(headerRenders).toBe(header);
  expect(stripRenders).toBe(strip);
});

it("a busy push asks once, a second later, for every shell pushed in that second", async () => {
  const view = render(<App />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  const settled = api.terminal_busy_many.mock.calls.length;
  runningIds = new Set(["s3", "s4"]);
  act(() => {
    push({ type: "terminal_busy", session_id: "s3", busy: true });
    push({ type: "terminal_busy", session_id: "s4", busy: true });
    push({ type: "terminal_busy", session_id: "s2", busy: false });
    push({ type: "terminal_busy", session_id: "unknown", busy: true });
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(999); });
  expect(api.terminal_busy_many.mock.calls.length).toBe(settled);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(api.terminal_busy_many.mock.calls.length).toBe(settled + 1);
  expect((api.terminal_busy_many.mock.calls.at(-1)![0] as string[]).sort()).toEqual(["s2", "s3", "s4"]);
  expect(view.getByTestId("running").textContent).toBe("s3,s4");
});

it("a close push shows the shell idle without a call", async () => {
  const view = render(<App />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  const settled = calls();
  act(() => push({ type: "terminal_close", session_id: "s2" }));
  expect(view.getByTestId("running").textContent).toBe("");
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(calls()).toBe(settled);
});
