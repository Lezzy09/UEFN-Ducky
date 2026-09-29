// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { useChatReferenceCatalog } from "../components/useChatReferenceCatalog";
import { findChatRefTokens, insertChatRef, parseChatRefHref } from "../components/chatReferences";
import { requestOpenChatReference } from "../navigation/openChatReference";
import { registerOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import { takePendingGraphFocus } from "../hooks/graphActivity";

const api = vi.hoisted(() => ({
  list_all_conversations: vi.fn().mockResolvedValue([]), list_agent_profiles: vi.fn().mockResolvedValue({ profiles: [] }),
  get_skill_info: vi.fn().mockResolvedValue({ packs: [] }), list_recent_projects: vi.fn().mockResolvedValue([]),
  list_project_file_paths: vi.fn().mockResolvedValue([]),
  list_workflows: vi.fn().mockResolvedValue({ workflows: [
    { id: "saved-id", name: "Build island", enabled: true, owner: { id: "local", kind: "local", label: "Local" } },
    { id: "team-id", name: "Nightly", enabled: true, owner: { id: "teamT", kind: "team", label: "Alpha Studio" } },
  ] }),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../hooks/usePluginContributions", () => { const value = { ui_panels: [], chat_references: [] }; return { usePluginContributions: () => value }; });
afterEach(cleanup);

it("offers saved workflows in slash references with their owner and preserves the request typed afterward", async () => {
  const { result } = renderHook(() => useChatReferenceCatalog(true, "chat"));
  await waitFor(() => expect(result.current.slashRefs.some((row) => row.href === "workflow:saved-id")).toBe(true));
  const ref = result.current.slashRefs.find((row) => row.href === "workflow:saved-id")!;
  expect(ref.group).toBe("Workflows");
  expect(ref.description).toMatch(/^Local · /);
  expect(result.current.slashRefs.find((row) => row.href === "workflow:team-id")?.description).toMatch(/^Team Alpha Studio · /);
  const inserted = insertChatRef("/build make a red tower", { trigger: "/", query: "build", start: 0, end: 6 }, ref.label, ref.href);
  expect(inserted.text).toContain("make a red tower");
  expect(findChatRefTokens(inserted.text)[0].href).toBe("workflow:saved-id");
  expect(parseChatRefHref(ref.href)).toEqual({ kind: "workflow", id: "saved-id" });
});

it("opens the referenced workflow in the editor without executing it, old pipeline links too", () => {
  const open = vi.fn();
  const unregister = registerOpenWorkflowsTab(open);
  requestOpenChatReference("workflow:saved-id", "Build island");
  expect(open).toHaveBeenCalledOnce();
  expect(takePendingGraphFocus()).toBe("saved-id");
  expect(findChatRefTokens("run [/Old](pipeline:old-id) now")[0].href).toBe("pipeline:old-id");
  requestOpenChatReference("pipeline:old-id", "Old");
  expect(open).toHaveBeenCalledTimes(2);
  expect(takePendingGraphFocus()).toBe("old-id");
  unregister();
});
