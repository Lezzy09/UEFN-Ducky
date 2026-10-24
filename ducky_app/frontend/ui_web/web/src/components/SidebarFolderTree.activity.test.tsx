// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FolderItem } from "../types/panel";
import { SidebarFolderTree } from "./SidebarFolderTree";

vi.mock("./ducky/DuckyAvatars", () => ({ DuckyAvatar: () => null, DUCKY_AVATAR_SIZES: { sidebar: 22 } }));
vi.mock("./editor/ChatTabHoverCard", () => ({ ChatTabHoverCard: ({ children }: { children: unknown }) => children }));
vi.mock("./editor/FolderTabHoverCard", () => ({ FolderTabHoverCard: ({ children }: { children: unknown }) => children }));
vi.mock("../hooks/usePluginContributions", () => ({ usePluginContributions: () => ({}), pluginContributesSettingsTab: () => false }));
vi.mock("../hooks/usePluginUiPrefs", () => ({ usePluginUiPrefs: () => ({ prefs: {}, setPref: () => {} }) }));
vi.mock("../voice/useLiveChatPresence", () => ({ useIsLiveChat: () => false }));
vi.mock("../voice/LiveChatMark", () => ({ LiveChatDot: () => null }));

// A tiny waiting-chats store the test drives (stands in for the ask-user / approval sources).
const waits = vi.hoisted(() => {
  let ids: ReadonlySet<string> = new Set<string>();
  const subs = new Set<() => void>();
  return {
    get: () => ids,
    set(next: string[]) {
      ids = new Set(next);
      subs.forEach((cb) => cb());
    },
    sub(cb: () => void) {
      subs.add(cb);
      return () => {
        subs.delete(cb);
      };
    },
    open: vi.fn(() => true),
  };
});
vi.mock("../hooks/waitingChats", async () => {
  const { useSyncExternalStore } = await import("react");
  const has = (id: string | null | undefined) => () => Boolean(id) && waits.get().has(String(id));
  return {
    useWaitingChatIds: () => useSyncExternalStore(waits.sub, waits.get, waits.get),
    useChatWaiting: (id: string | null | undefined) => useSyncExternalStore(waits.sub, has(id), has(id)),
    useNeedsYou: (id: string | null | undefined) =>
      useSyncExternalStore(waits.sub, has(id), has(id)) ? { kind: "question", since: 3 } : null,
    openWaitingChat: waits.open,
  };
});

type Chat = FolderItem["chats"][number];
const members: Chat[] = ["m1", "m2", "m3", "m4"].map((id) => ({ id, name: `Stub ${id}`, parentConvId: "engine-hub" }));
const engine = (expanded: boolean): FolderItem => ({
  id: "engine", name: "Engine", parentId: "", sortOrder: 0, expanded, chats: members, children: [], groupHubId: "engine-hub",
});

let pushFolders: (f: FolderItem[]) => void = () => {};

function Harness({ running, expanded = false }: { running: Set<string>; expanded?: boolean }) {
  const [folders, setFolders] = useState<FolderItem[]>([engine(expanded)]);
  pushFolders = setFolders;
  const [rootChats, setRootChats] = useState<Chat[]>([]);
  const [editing, setEditing] = useState<{ kind: "folder" | "chat"; id: string; value: string } | null>(null);
  return (
    <SidebarFolderTree
      folders={folders} setFolders={setFolders} rootChats={rootChats} setRootChats={setRootChats}
      archiveChats={[]} load={async () => {}} activeChats={[]} runningChatIds={running}
      onChatSelect={() => {}} newlyCreatedIds={new Set()} editing={editing} setEditing={setEditing}
      editInputRef={createRef<HTMLInputElement>()} onCommitRename={() => {}} onCancelRename={() => {}}
      onRenameFolder={() => {}} onDeleteFolder={() => {}} onRenameChat={() => {}} onDeleteChat={() => {}}
      onFocusChat={() => {}} onEditDucky={() => {}} selectedChatFolderId={null} onSelectChatFolder={() => {}}
      onCreateDucky={() => {}} onCreateGroup={() => {}} currentProjectSlug="here"
    />
  );
}

const api = {
  get_listener_status: vi.fn(),
  apply_sidebar_layout: vi.fn().mockResolvedValue(undefined),
  group_members: vi.fn(async () => ({ ok: true, members: [] })),
  get_plan: vi.fn(async () => ({ ok: false })),
};

const engineBranch = () => document.querySelector('[data-tree-node="folder:engine"]') ?? screen.getByText("Engine").closest(".sidebar-tree-branch")!;

beforeEach(() => {
  window.pywebview = { api } as unknown as typeof window.pywebview;
  waits.set([]);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete window.pywebview;
});

describe("activity on collapsed sidebar rows", () => {
  it("20 member updates keep a collapsed group shut; its row shows the dot and 'N running'", async () => {
    const { rerender } = render(<Harness running={new Set()} />);
    await screen.findByText("Engine");
    for (let i = 0; i < 20; i++) {
      const running = new Set(members.slice(0, (i % 3) + 1).map((m) => m.id));
      // Each chats-changed reload hands the tree fresh rows that keep the saved open state.
      act(() => pushFolders([engine(false)]));
      rerender(<Harness running={running} />);
    }
    const branch = engineBranch();
    expect(branch.className).toContain("sidebar-tree-branch-collapsed");
    expect(branch.querySelector(".sidebar-agent-spinner")).toBeTruthy();
    // 20th update: i = 19 → 19 % 3 + 1 = 2 running.
    expect(screen.getByText("2 running")).toBeTruthy();
  });

  it("an open group shows no running count on its row", async () => {
    render(<Harness running={new Set(["m1"])} expanded />);
    await screen.findByText("Stub m1");
    expect(screen.queryByText("1 running")).toBeNull();
  });

  it("'Needs you' on a waiting chat's row opens it at the card; answering clears it", async () => {
    render(<Harness running={new Set()} expanded />);
    await screen.findByText("Stub m2");
    expect(screen.queryByText("Needs you")).toBeNull();
    act(() => waits.set(["m2"]));
    const badge = screen.getByText("Needs you");
    expect(badge.closest("[data-sidebar-id]")?.textContent).toContain("Stub m2");
    fireEvent.click(badge);
    expect(waits.open).toHaveBeenCalledWith("m2", "Stub m2");
    act(() => waits.set([]));
    expect(screen.queryByText("Needs you")).toBeNull();
  });

  it("a collapsed folder counts its waiting chats next to its running count", async () => {
    render(<Harness running={new Set(["m1", "m3"])} />);
    await screen.findByText("Engine");
    act(() => waits.set(["m2", "m4"]));
    expect(screen.getByText("2 running")).toBeTruthy();
    fireEvent.click(screen.getByText("2 need you"));
    expect(waits.open).toHaveBeenCalledWith("m2", "");
    act(() => waits.set([]));
    expect(screen.queryByText(/need/)).toBeNull();
  });
});
