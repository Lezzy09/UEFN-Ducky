// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { fileRefsOf, filePathsOf, useFileRefMatches } from "./useChatReferenceCatalog";

const api = vi.hoisted(() => ({ list_project_file_paths: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../hooks/usePluginContributions", () => ({ usePluginContributions: () => ({ ui_panels: [], chat_references: [] }) }));
vi.mock("../verse-editor/utils/isVerseFile", () => ({ isFolderProject: () => true, isAbsEncodedPath: () => false }));

beforeEach(() => {
  vi.useFakeTimers();
  api.list_project_file_paths.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("reads the new reply shape into file refs named by the last segment", () => {
  const refs = fileRefsOf(filePathsOf({ paths: ["docs/readme.md", "Content\\a\\b.verse", "x.png"], total: 3, truncated: false }));
  expect(refs.map((ref) => [ref.label, ref.href])).toEqual([
    ["readme.md", "file:docs/readme.md"],
    ["b.verse", "file:Content/a/b.verse"],
  ]);
  expect(filePathsOf([])).toEqual([]);
});

it("finds a deep file past the first 2,000 through the query call", async () => {
  api.list_project_file_paths.mockResolvedValue({ paths: ["backend/tools/panel/ducky_swarm.md"], truncated: false });
  const local = fileRefsOf(["docs/readme.md"]);
  const { result } = renderHook(() => useFileRefMatches("ducky_swarm", true, local));
  expect(result.current).toEqual([]);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
  expect(api.list_project_file_paths).toHaveBeenCalledOnce();
  expect(api.list_project_file_paths).toHaveBeenCalledWith("ducky_swarm", 50);
  expect(result.current.map((ref) => ref.href)).toEqual(["file:backend/tools/panel/ducky_swarm.md"]);
});

it("skips the server when the local list already has 10 hits", async () => {
  const local = fileRefsOf(Array.from({ length: 12 }, (_, i) => `docs/note${i}.md`));
  const { result } = renderHook(() => useFileRefMatches("note", true, local));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
  expect(api.list_project_file_paths).not.toHaveBeenCalled();
  expect(result.current).toHaveLength(12);
});
