// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { duckiesLayoutHold } from "../utils/duckiesLayoutHold";
import { useChatFolders } from "./useChatFolders";

afterEach(() => {
  cleanup();
  delete window.pywebview;
});

const conv = (id: string, extra: Record<string, unknown> = {}) => ({ id, title: id, ...extra });

function install(api: Record<string, unknown>) {
  window.pywebview = { api: { get_listener_status: vi.fn(), ...api } } as unknown as typeof window.pywebview;
}

it("shows every ducky, group and folder as one list, with no project rows", async () => {
  install({
    list_folders: vi.fn().mockResolvedValue([
      { id: "squad", name: "Squad", parent_id: "", sort_order: 0, group_hub_id: "hub" },
      { id: "notes", name: "Notes", parent_id: "squad", sort_order: 0 },
    ]),
    list_all_conversations: vi.fn().mockResolvedValue([
      conv("c1"),
      conv("hub", { folder_id: "squad", is_group: true }),
      conv("m1", { folder_id: "squad" }),
      conv("old", { folder_id: "archive" }),
    ]),
  });
  const { result } = renderHook(() => useChatFolders(0));
  await waitFor(() => expect(result.current.foldersLoaded).toBe(true));
  expect(result.current.rootChats.map((c) => c.id)).toEqual(["c1"]);
  expect(result.current.folders.map((f) => f.id)).toEqual(["squad"]);
  expect(result.current.folders[0].chats.map((c) => c.id)).toEqual(["m1"]);
  expect(result.current.folders[0].children.map((f) => f.id)).toEqual(["notes"]);
  expect(result.current.archiveChats.map((c) => c.id)).toEqual(["old"]);
  // Group hubs stay findable for their chat tabs.
  expect(result.current.hubChats.map((c) => c.id)).toEqual(["hub"]);
});

it("shows top-level duckies in their saved order", async () => {
  install({
    list_folders: vi.fn().mockResolvedValue([]),
    list_all_conversations: vi.fn().mockResolvedValue([
      conv("one", { sort_order: 1 }),
      conv("two", { sort_order: 0 }),
      conv("three", { sort_order: 2 }),
    ]),
  });
  const { result } = renderHook(() => useChatFolders(0));
  await waitFor(() => expect(result.current.foldersLoaded).toBe(true));
  expect(result.current.rootChats.map((c) => c.id)).toEqual(["two", "one", "three"]);
});

it("drops deleted rows at once, and a slower older answer never brings them back", async () => {
  let release: (rows: unknown[]) => void = () => {};
  const list = vi.fn()
    .mockImplementationOnce(async () => [conv("c1"), conv("c2")])
    .mockImplementationOnce(async () => [])
    .mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }))
    .mockImplementation(async () => []);
  install({ list_folders: vi.fn().mockResolvedValue([]), list_all_conversations: list });
  const { result } = renderHook(() => useChatFolders(0));
  await waitFor(() => expect(result.current.rootChats.map((c) => c.id)).toEqual(["c1", "c2"]));
  // A reload starts (it will answer late, with c2 still there)…
  let slow: Promise<void> = Promise.resolve();
  act(() => { slow = result.current.load(); });
  // …then another window deletes c2.
  act(() => result.current.removeRows(["c2"], []));
  expect(result.current.rootChats.map((c) => c.id)).toEqual(["c1"]);
  await act(async () => {
    release([conv("c1"), conv("c2")]);
    await slow;
  });
  expect(result.current.rootChats.map((c) => c.id)).toEqual(["c1"]);
});

it("never paints a reload over a move that is still saving", async () => {
  const rows = [conv("c1"), conv("c2")];
  install({
    list_folders: vi.fn().mockResolvedValue([]),
    list_all_conversations: vi.fn().mockImplementation(async (all?: boolean) => (all ? [] : rows)),
  });
  const { result } = renderHook(() => useChatFolders(0));
  await waitFor(() => expect(result.current.rootChats.map((c) => c.id)).toEqual(["c1", "c2"]));
  const releaseHold = duckiesLayoutHold.hold();
  act(() => result.current.setRootChats([{ id: "c2", name: "c2" }, { id: "c1", name: "c1" }]));
  await act(async () => { await result.current.load(); });
  expect(result.current.rootChats.map((c) => c.id)).toEqual(["c2", "c1"]); // the moved order stays
  // The save finished: the host's order (now c2, c1) is loaded once.
  rows.reverse();
  await act(async () => { releaseHold(); });
  await waitFor(() => expect(result.current.rootChats.map((c) => c.id)).toEqual(["c2", "c1"]));
});
