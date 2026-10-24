// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatPlan, FolderItem, GroupMemberDto, PlanNode } from "../types/panel";
import { SidebarFolderTree } from "./SidebarFolderTree";

vi.mock("./ducky/DuckyAvatars", () => ({ DuckyAvatar: () => null, DUCKY_AVATAR_SIZES: { sidebar: 22 } }));
vi.mock("./editor/ChatTabHoverCard", () => ({ ChatTabHoverCard: ({ children }: { children: unknown }) => children }));
vi.mock("./editor/FolderTabHoverCard", () => ({ FolderTabHoverCard: ({ children }: { children: unknown }) => children }));
vi.mock("../hooks/usePluginContributions", () => ({ usePluginContributions: () => ({}), pluginContributesSettingsTab: () => false }));
vi.mock("../hooks/usePluginUiPrefs", () => ({ usePluginUiPrefs: () => ({ prefs: {}, setPref: () => {} }) }));
vi.mock("../voice/useLiveChatPresence", () => ({ useIsLiveChat: () => false }));
vi.mock("../voice/LiveChatMark", () => ({ LiveChatDot: () => null }));

type Chat = FolderItem["chats"][number];
const folder = (id: string, chats: Chat[] = [], children: FolderItem[] = [], extra: Partial<FolderItem> = {}): FolderItem =>
  ({ id, name: id, parentId: "", sortOrder: 0, expanded: true, chats, children, ...extra });

const section = (id: string, done: number, total: number): PlanNode => ({
  id, content: id, status: "in_progress", kind: "subplan",
  children: Array.from({ length: total }, (_, i) => ({
    id: `${id}-${i}`, content: `${id} step ${i + 1}`, status: i < done ? "completed" : i === done ? "in_progress" : "pending",
  })),
});
const plan: ChatPlan = {
  id: "team-plan", chat_id: "lead", title: "Shop island", todos: [],
  nodes: [section("art", 3, 10), section("verse", 3, 5), section("narr", 2, 4)],
};
const seat = (id: string, hub: string, node_id: string): GroupMemberDto => ({
  member_conv_id: id, profile_id: "", name: id,
  observation: { observed_at: 0, runtime: "idle", group_id: hub, project_slug: null, role: "member",
    assignment: { plan_id: "team-plan", chat_id: "lead", node_id, title: id, status: "in_progress" } },
});
const rosters: Record<string, GroupMemberDto[]> = {
  "art-hub": [seat("art-m1", "art-hub", "art")],
  "code-hub": [seat("verse", "code-hub", "verse")],
  "team-hub": [seat("narr", "team-hub", "narr")],
};

const api = {
  get_listener_status: vi.fn(),
  apply_sidebar_layout: vi.fn().mockResolvedValue(undefined),
  group_members: vi.fn(async (id: string) => ({ ok: true, members: rosters[id] || [] })),
  get_plan: vi.fn(async () => ({ ok: true, plan })),
  set_muted: vi.fn(async (id: string, muted: boolean) => ({ ok: true, id, muted })),
};

/** A muted group (Art), and an open group (Team) holding a muted chat and a muted sub-group (Code). */
function Harness({ onChatSelect }: { onChatSelect: (c: { id: string }) => void }) {
  const [folders, setFolders] = useState<FolderItem[]>([
    folder("Art", [{ id: "art-m1", name: "art-m1" }], [], { groupHubId: "art-hub", muted: true }),
    folder("Team", [{ id: "narr", name: "Narrative lead", muted: true, parentConvId: "team-hub" }], [
      folder("Code", [{ id: "verse", name: "Verse lead" }], [], { groupHubId: "code-hub", muted: true }),
    ], { groupHubId: "team-hub" }),
  ]);
  const [rootChats, setRootChats] = useState<Chat[]>([]);
  const [editing, setEditing] = useState<{ kind: "folder" | "chat"; id: string; value: string } | null>(null);
  return (
    <SidebarFolderTree
      folders={folders} setFolders={setFolders} rootChats={rootChats} setRootChats={setRootChats}
      archiveChats={[]} load={async () => {}} activeChats={[]} runningChatIds={new Set()}
      onChatSelect={onChatSelect} newlyCreatedIds={new Set()} editing={editing} setEditing={setEditing}
      editInputRef={createRef<HTMLInputElement>()} onCommitRename={() => {}} onCancelRename={() => {}}
      onRenameFolder={() => {}} onDeleteFolder={() => {}} onRenameChat={() => {}} onDeleteChat={() => {}}
      onFocusChat={() => {}} onEditDucky={() => {}} selectedChatFolderId={null} onSelectChatFolder={() => {}}
      onCreateDucky={() => {}} onCreateGroup={() => {}} currentProjectSlug="here"
    />
  );
}

beforeEach(() => {
  window.pywebview = { api } as unknown as typeof window.pywebview;
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete window.pywebview;
});

describe("muted rows in the Duckies tree", () => {
  it("a muted group is one row with its rollup that never shows its chats", async () => {
    render(<Harness onChatSelect={() => {}} />);
    await screen.findByText("Art · 30% · MUTED");
    expect(screen.queryByText("art-m1")).toBeNull();
    // No expand chevron on the muted row (the open Team group keeps its own).
    const artRow = screen.getByText("Art · 30% · MUTED").closest("[data-tree-node]")!;
    expect(artRow.querySelector("[aria-expanded]")).toBeNull();
  });

  it("a muted chat is a progress row that doesn't open the chat", async () => {
    const onChatSelect = vi.fn();
    render(<Harness onChatSelect={onChatSelect} />);
    const meta = await screen.findByText("2/4 · narr step 3");
    fireEvent.click(screen.getByText("Narrative lead"));
    expect(onChatSelect).not.toHaveBeenCalled();
    expect(meta).toBeTruthy();
  });

  it("a muted sub-group inside an open group is one row; the open group still shows its rows", async () => {
    render(<Harness onChatSelect={() => {}} />);
    await screen.findByText("Code · 60% · MUTED");
    expect(screen.queryByText("Verse lead")).toBeNull();
    expect(screen.getByText("Team")).toBeTruthy();
    expect(screen.getByText("Narrative lead")).toBeTruthy();
  });

  it("right-click Unmute and Mute call set_muted on the hub or the chat", async () => {
    render(<Harness onChatSelect={() => {}} />);
    fireEvent.contextMenu(await screen.findByText("Code · 60% · MUTED"));
    fireEvent.click(await screen.findByText("Unmute"));
    expect(api.set_muted).toHaveBeenCalledWith("code-hub", false);
    fireEvent.contextMenu(screen.getByText("Team"));
    fireEvent.click(await screen.findByText("Mute"));
    await waitFor(() => expect(api.set_muted).toHaveBeenCalledWith("team-hub", true));
  });
});
