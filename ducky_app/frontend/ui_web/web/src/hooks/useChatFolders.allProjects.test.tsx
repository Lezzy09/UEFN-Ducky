// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useChatFolders } from "./useChatFolders";

vi.mock("../utils/duckiesTreePrefs", () => ({ readDuckiesAllProjects: () => true }));

afterEach(() => {
  cleanup();
  delete window.pywebview;
});

it("hides projects with no duckies but keeps the open one", async () => {
  window.pywebview = { api: {} } as typeof window.pywebview;
  const { result } = renderHook(() => useChatFolders(0, "here"));
  await act(async () => {
    window.pywebview = {
      api: {
        get_listener_status: vi.fn(),
        list_folders: vi.fn().mockResolvedValue([]),
        list_all_conversations: vi.fn().mockResolvedValue([
          { id: "c1", title: "Ducky", folder_id: "", project_slug: "busy", project_name: "Busy" },
        ]),
        list_recent_projects: vi.fn().mockResolvedValue([
          { slug: "empty_island", name: "Empty", path: "C:/islands/Empty", active: false },
          { slug: "here", name: "Here", path: "C:/islands/Here", active: true },
        ]),
      },
    } as unknown as typeof window.pywebview;
    window.dispatchEvent(new Event("pywebviewready"));
  });
  await waitFor(() => expect(result.current.foldersLoaded).toBe(true));
  // Global Agents is always there, even empty, so duckies can be dropped into it.
  const ids = result.current.folders.map((folder) => folder.id);
  expect(ids).toContain("project:here");
  expect(ids).toContain("project:busy");
  expect(ids).toContain("project:_no_project");
  expect(ids).not.toContain("project:empty_island");
});
