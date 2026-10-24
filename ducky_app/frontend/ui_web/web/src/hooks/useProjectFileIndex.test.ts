// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { useProjectFileIndex } from "./useProjectFileIndex";

const api = vi.hoisted(() => ({
  list_project_file_paths: vi.fn().mockResolvedValue({
    paths: ["Content/Verse/game.verse", "backend\\tools\\panel\\ducky_swarm.py"],
    total: 20000,
    truncated: true,
  }),
}));
vi.mock("./usePanelApi", () => ({ getApi: () => api }));
afterEach(cleanup);

it("fills the index from the {paths, total, truncated} reply with names from the last path segment", async () => {
  const { result } = renderHook(() => useProjectFileIndex(true));
  await waitFor(() => expect(result.current.files).toHaveLength(2));
  expect(result.current.files[0]).toEqual({ path: "Content/Verse/game.verse", name: "game.verse" });
  expect(result.current.files[1].name).toBe("ducky_swarm.py");
});
