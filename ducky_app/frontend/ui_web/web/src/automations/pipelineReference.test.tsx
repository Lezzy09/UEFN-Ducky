// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { useChatReferenceCatalog } from "../components/useChatReferenceCatalog";
import { findChatRefTokens, insertChatRef, parseChatRefHref } from "../components/chatReferences";
import { requestOpenChatReference } from "../navigation/openChatReference";
import { registerOpenPipelinesTab } from "../navigation/openPipelinesTab";
import { takePendingGraphFocus } from "../hooks/graphActivity";

const api = vi.hoisted(() => ({
  list_all_conversations: vi.fn().mockResolvedValue([]), list_agent_profiles: vi.fn().mockResolvedValue({ profiles: [] }),
  get_skill_info: vi.fn().mockResolvedValue({ packs: [] }), list_recent_projects: vi.fn().mockResolvedValue([]),
  list_project_file_paths: vi.fn().mockResolvedValue([]), list_pipelines: vi.fn().mockResolvedValue({ pipelines: [{ id: "saved-id", name: "Build island" }] }),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../hooks/usePluginContributions", () => { const value = { ui_panels: [], chat_references: [] }; return { usePluginContributions: () => value }; });
afterEach(cleanup);

it("offers saved pipelines in slash references and preserves the request typed afterward", async () => {
  const { result } = renderHook(() => useChatReferenceCatalog(true, "chat"));
  await waitFor(() => expect(result.current.slashRefs.some((row) => row.href === "pipeline:saved-id")).toBe(true));
  const ref = result.current.slashRefs.find((row) => row.href === "pipeline:saved-id")!;
  const inserted = insertChatRef("/build make a red tower", { trigger: "/", query: "build", start: 0, end: 6 }, ref.label, ref.href);
  expect(inserted.text).toContain("make a red tower");
  expect(findChatRefTokens(inserted.text)[0].href).toBe("pipeline:saved-id");
  expect(parseChatRefHref(ref.href)).toEqual({ kind: "pipeline", id: "saved-id" });
});

it("opens the referenced pipeline in its editor without executing it", () => {
  const open = vi.fn();
  const unregister = registerOpenPipelinesTab(open);
  requestOpenChatReference("pipeline:saved-id", "Build island");
  expect(open).toHaveBeenCalledOnce();
  expect(takePendingGraphFocus("pipeline")).toBe("saved-id");
  unregister();
});
