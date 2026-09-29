// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ProjectFileListing } from "../types/panel";
import { contentRootPath } from "../verse-editor/utils/isVerseFile";
import { useWorkspaceTreeData } from "./useWorkspaceTreeData";

const api = vi.hoisted(() => ({
  get_project_info: vi.fn(),
  list_project_files: vi.fn(),
  list_workspace_roots: vi.fn(),
}));
vi.mock("./usePanelApi", () => ({ getApi: () => api }));
vi.mock("./onApiReady", () => ({ onApiReady: (fn: () => void) => { fn(); return () => {}; } }));
afterEach(cleanup);

it("a folder project's first load lists the folder root, never a missing Content/", async () => {
  api.get_project_info.mockResolvedValue({ path: "C:/repo", name: "repo", slug: "repo_1", kind: "folder", content_root: "." });
  const roots: ProjectFileListing = {
    path: "__roots__",
    entries: [{ name: "repo", path: "ws:0", is_dir: true, read_only: false, kind: "content" }],
  };
  api.list_project_files.mockImplementation(async (path: string) =>
    path === "__roots__" ? roots : { path, entries: [{ name: "src", path: "src", is_dir: true }] },
  );
  api.list_workspace_roots.mockResolvedValue([{ id: "ws:0", name: "repo", path: "C:/repo", read_only: false }]);
  const expandedRef = { current: new Set<string>() };
  const { result } = renderHook(() => useWorkspaceTreeData("_no_project", 0, true, expandedRef));
  await act(async () => {});
  expect(contentRootPath()).toBe(".");
  expect(api.list_project_files.mock.calls.map(([path]) => path)).not.toContain("Content");
  expect(result.current.error).toBeNull();
  expect(result.current.cache.get(".")?.[0]?.path).toBe("src");
  expect(result.current.cache.get("ws:0")?.[0]?.path).toBe("src");
});
