// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AgentEvent, GroupMemberDto } from "../../types/panel";

const api = vi.hoisted(() => ({ group_members: vi.fn() }));
vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => api }));
const listeners = vi.hoisted(() => new Set<(event: AgentEvent) => void>());
vi.mock("../../hooks/useAgentEventBus", () => ({
  subscribeAgentEvents: (fn: (event: AgentEvent) => void) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
}));

import { loadRoster, resetRosterStore, setRoster, useRoster, useRosters } from "./rosterStore";

const member = (id: string, extra: Partial<GroupMemberDto> = {}): GroupMemberDto =>
  ({ name: id, profile_id: "", member_conv_id: id, ...extra }) as GroupMemberDto;
const push = (event: Record<string, unknown>) => act(() => { for (const fn of [...listeners]) fn(event as AgentEvent); });
const groups = ["g1", "g2", "g3", "g4", "g5", "g6"];
let rosters: Record<string, GroupMemberDto[]> = {};
const callsFor = (id: string) => api.group_members.mock.calls.filter(([g]) => g === id).length;

beforeEach(() => {
  vi.useFakeTimers();
  rosters = Object.fromEntries(groups.map((g) => [g, [member(`${g}-a`)]]));
  api.group_members.mockImplementation(async (id: string) => ({ ok: true, members: rosters[id] ?? [] }));
});
afterEach(() => {
  cleanup();
  resetRosterStore();
  vi.useRealTimers();
  vi.resetAllMocks();
});

it("a team with 6 nested groups costs 6 calls once and none on re-render", async () => {
  const { result, rerender } = renderHook(() => useRosters(groups));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(api.group_members).toHaveBeenCalledTimes(6);
  expect(Object.keys(result.current).sort()).toEqual(groups);

  for (let i = 0; i < 5; i++) rerender();
  // A second view of the same groups (the team bar and the sidebar) shares the cache.
  renderHook(() => useRosters([...groups].reverse()));
  await loadRoster("g3");
  await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000); });
  expect(api.group_members).toHaveBeenCalledTimes(6);
});

it("a member-added push refreshes that group only, once per burst", async () => {
  const { result } = renderHook(() => useRosters(groups));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  api.group_members.mockClear();
  rosters.g2 = [member("g2-a"), member("g2-b")];

  push({ type: "chats_changed", conv_id: "g2" });
  push({ type: "chats_changed", conv_id: "g2" });
  push({ type: "chats_changed", conv_id: "not-a-group" });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });

  expect(api.group_members).toHaveBeenCalledTimes(1);
  expect(api.group_members).toHaveBeenCalledWith("g2");
  expect(result.current.g2.map((m) => m.member_conv_id)).toEqual(["g2-a", "g2-b"]);
  expect(result.current.g1.map((m) => m.member_conv_id)).toEqual(["g1-a"]);
});

it("member activity refreshes a watched group within 5 s; a mutation reply needs no call", async () => {
  const { result } = renderHook(() => useRoster("g1"));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(callsFor("g1")).toBe(1);

  push({ type: "agent_started", conv_id: "g1-a" });
  push({ type: "agent_stopped", conv_id: "g1-a" });
  push({ type: "agent_started", conv_id: "someone-else" });
  await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
  expect(callsFor("g1")).toBe(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(callsFor("g1")).toBe(2);

  act(() => setRoster("g1", [member("g1-a"), member("g1-z")], "g1-z"));
  expect(result.current?.members.map((m) => m.member_conv_id)).toEqual(["g1-a", "g1-z"]);
  expect(result.current?.leaderConvId).toBe("g1-z");
  expect(callsFor("g1")).toBe(2);
});

it("an unwatched cached group is dropped by a push and read again on next use", async () => {
  await loadRoster("g4");
  expect(callsFor("g4")).toBe(1);
  push({ type: "chats_changed", conv_id: "g4" });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(callsFor("g4")).toBe(1);
  await loadRoster("g4");
  expect(callsFor("g4")).toBe(2);
});
