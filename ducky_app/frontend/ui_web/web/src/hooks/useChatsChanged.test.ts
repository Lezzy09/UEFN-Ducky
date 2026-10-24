// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "../types/panel";
import { RELOAD_BATCH_MS, requestReloadDuckies, shouldOpenCreatedChat, useChatsChanged } from "./useChatsChanged";
import { useChatFolders } from "./useChatFolders";

const bus = vi.hoisted(() => ({ listeners: new Set<(event: AgentEvent) => void>() }));
vi.mock("./useAgentEventBus", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./useAgentEventBus")>()),
  installAgentEventBus: () => {},
  subscribeAgentEvents: (listener: (event: AgentEvent) => void) => {
    bus.listeners.add(listener);
    return () => bus.listeners.delete(listener);
  },
}));
const emit = (event: AgentEvent) => bus.listeners.forEach((listener) => listener(event));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  delete window.pywebview;
});

describe("shouldOpenCreatedChat", () => {
  it("opens a new chat by default but not when open is false", () => {
    expect(shouldOpenCreatedChat({ type: "chats_changed", conv_id: "g1" })).toBe(true);
    expect(shouldOpenCreatedChat({ type: "chats_changed", conv_id: "g1", open: false })).toBe(false);
    expect(shouldOpenCreatedChat({ type: "chats_changed", open: false })).toBe(false);
  });
});

describe("useChatsChanged batching", () => {
  it("runs one trailing load per window; removals and reload requests still land", () => {
    vi.useFakeTimers();
    const load = vi.fn().mockResolvedValue(undefined);
    const onRemoved = vi.fn();
    renderHook(() => useChatsChanged(load, undefined, onRemoved));
    emit({ type: "chats_changed", removed_conv_ids: ["gone"] });
    requestReloadDuckies();
    emit({ type: "chats_changed" });
    expect(onRemoved).toHaveBeenCalledWith(["gone"], []);
    expect(load).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(RELOAD_BATCH_MS); });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("100 member events in 1 s: at most 3 list_folders calls and 3 tree renders", async () => {
    vi.useFakeTimers();
    const listFolders = vi.fn().mockResolvedValue([]);
    let convs = [{ id: "lead", title: "Lead" }];
    window.pywebview = { api: {
      get_listener_status: vi.fn(), list_folders: listFolders,
      list_all_conversations: vi.fn(async () => convs),
    } } as unknown as typeof window.pywebview;
    let treeRenders = 0;
    let lastRoot: unknown;
    const { result } = renderHook(() => {
      const folders = useChatFolders(0);
      useChatsChanged(folders.load);
      if (folders.rootChats !== lastRoot) { treeRenders += 1; lastRoot = folders.rootChats; }
      return folders;
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.foldersLoaded).toBe(true);
    listFolders.mockClear();
    treeRenders = 0;

    for (let i = 0; i < 100; i++) {
      if (i === 50) convs = [...convs, { id: "m1", title: "Member" }];
      await act(async () => {
        emit({ type: "chats_changed", conv_id: "lead", open: false });
        await vi.advanceTimersByTimeAsync(10);
      });
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(RELOAD_BATCH_MS); });

    expect(listFolders.mock.calls.length).toBeGreaterThan(0);
    expect(listFolders.mock.calls.length).toBeLessThanOrEqual(3);
    expect(treeRenders).toBeLessThanOrEqual(3);
    expect(result.current.rootChats.map((chat) => chat.id)).toEqual(["lead", "m1"]);
  });

  it("a no-op load keeps the same tree objects (no setFolders)", async () => {
    window.pywebview = { api: {
      get_listener_status: vi.fn(),
      list_folders: vi.fn().mockResolvedValue([{ id: "f1", name: "Team", parent_id: null }]),
      list_all_conversations: vi.fn().mockResolvedValue([{ id: "a", title: "A", folder_id: "f1" }]),
    } } as unknown as typeof window.pywebview;
    const { result } = renderHook(() => useChatFolders(0));
    await act(async () => { await result.current.load(); });
    const folders = result.current.folders;
    const rootChats = result.current.rootChats;
    expect(folders.length).toBe(1);
    await act(async () => { await result.current.load(); });
    expect(result.current.folders).toBe(folders);
    expect(result.current.rootChats).toBe(rootChats);
  });
});
