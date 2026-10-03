// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { DndContext } from "@dnd-kit/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FolderItem } from "../../types/panel";
import { projectFolderId } from "../../utils/sidebarTree";
import { GlobalAgentsSection } from "./GlobalAgentsSection";

vi.mock("../ducky/DuckyAvatars", () => ({ DuckyAvatar: () => null, DUCKY_AVATAR_SIZES: { sidebar: 22 } }));

function bucket(chats: FolderItem["chats"]): FolderItem {
  return {
    id: projectFolderId("_no_project"),
    name: "No project",
    parentId: "",
    expanded: true,
    sortOrder: 0,
    chats,
    children: [],
  };
}

const opened = vi.fn();
const deleted = vi.fn();
const renamed = vi.fn();
const created = vi.fn();

function mount(folders: FolderItem[]) {
  return render(
    <DndContext>
      <GlobalAgentsSection
        folders={folders}
        compact
        filterQuery=""
        activeChats={[]}
        onOpenChat={opened}
        onDeleteChat={deleted}
        onRenameChat={renamed}
        onCreate={created}
      />
    </DndContext>,
  );
}

afterEach(() => {
  cleanup();
  opened.mockReset();
  deleted.mockReset();
  renamed.mockReset();
  created.mockReset();
});

describe("global agents", () => {
  it("lists duckies with no project and leaves island duckies out", () => {
    mount([
      bucket([{ id: "loose", name: "Loose Ducky" }]),
      {
        id: projectFolderId("island"),
        name: "UEFN-Ducky-Release",
        parentId: "",
        expanded: true,
        sortOrder: 1,
        chats: [{ id: "verse", name: "Verse Coder" }],
        children: [],
      },
    ]);
    expect(screen.getByRole("button", { name: "Loose Ducky", exact: true })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Verse Coder", exact: true })).toBeNull();
  });

  it("adds a projectless ducky from the header and archives the chat, not a template", () => {
    mount([bucket([{ id: "loose", name: "Loose Ducky" }])]);
    fireEvent.click(screen.getByTitle("Add a ducky with no project"));
    expect(created).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTitle("Archive"));
    expect(deleted).toHaveBeenCalledExactlyOnceWith("loose", "Loose Ducky");
  });
});
