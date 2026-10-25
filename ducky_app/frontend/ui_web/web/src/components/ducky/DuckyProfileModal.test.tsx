// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DuckyProfileModal, type DuckyProfileModalMode } from "./DuckyProfileModal";

vi.mock("../../contexts/ConfirmModalContext", () => ({
  useConfirmModal: () => ({ confirm: vi.fn(), alert: vi.fn() }),
}));
vi.mock("../../hooks/useHasApiKey", () => ({ useHasApiKey: () => true }));
vi.mock("../../hooks/usePluginContributions", () => ({
  usePluginContributions: () => ({ llm_providers: [], llm_coding_agents: [], ready: true }),
}));
vi.mock("./DuckyCatalogContext", () => {
  const catalog = { allStyles: [], defaultStyle: "artist", normalizeStyle: (id: string) => id };
  return { useDuckyCatalog: () => catalog };
});
vi.mock("../Modal", () => ({
  Modal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ModalActions: () => null,
}));
vi.mock("./DuckyProfileEditorForm", () => ({ DuckyProfileEditorForm: () => null }));
vi.mock("./DuckyProfilePicker", () => ({
  DuckyProfilePicker: ({ profiles }: { profiles: { id: string; name: string }[] }) =>
    <div>{profiles.map((p) => <span key={p.id}>{p.name}</span>)}</div>,
}));

const state: DuckyProfileModalMode = { mode: "create", folders: [], rootChats: [] };
const catalog = { packs: [], tools: [], default_disabled_packs: [], default_disabled_tool_ids: [] };

function apiWithCatalog(getCatalog: ReturnType<typeof vi.fn>) {
  return {
    get_listener_status: vi.fn(),
    list_agent_profiles: vi.fn().mockResolvedValue({
      profiles: [{ id: "saved", name: "Saved agent" }],
    }),
    get_agent_profile_editor_catalog: getCatalog,
  };
}

afterEach(() => {
  cleanup();
  delete window.pywebview;
});
// Order matters: the first two run cold, before any open has filled the cache.
it("waddles while the native API arrives after the dialog opens, never Loading text", async () => {
  window.pywebview = { api: {} } as typeof window.pywebview;
  render(<DuckyProfileModal open state={state} onClose={vi.fn()} />);
  expect(screen.getByRole("status", { name: "Getting your duckies" })).toBeTruthy();
  expect(screen.queryByText("Loading…")).toBeNull();
  await act(async () => {
    window.pywebview = { api: apiWithCatalog(vi.fn().mockResolvedValue(catalog)) } as unknown as typeof window.pywebview;
    window.dispatchEvent(new Event("pywebviewready"));
  });
  await waitFor(() => expect(screen.getByText("Saved agent")).toBeTruthy());
});

it("reopens on the cached list at once and refreshes behind", async () => {
  const getCatalog = vi.fn().mockReturnValue(new Promise(() => {}));
  window.pywebview = { api: apiWithCatalog(getCatalog) } as unknown as typeof window.pywebview;
  render(<DuckyProfileModal open state={state} onClose={vi.fn()} />);
  expect(screen.getByText("Saved agent")).toBeTruthy();
  expect(screen.queryByRole("status", { name: "Getting your duckies" })).toBeNull();
  expect(getCatalog).toHaveBeenCalledTimes(1);
});

it("shows a catalog failure on an edit and can retry", async () => {
  const getCatalog = vi.fn().mockRejectedValueOnce(new Error("Invalid skill version"))
    .mockResolvedValue(catalog);
  window.pywebview = { api: { ...apiWithCatalog(getCatalog), get_chat_mcp_plugins: vi.fn(), get_conversation_skills: vi.fn() } } as unknown as typeof window.pywebview;
  const edit = { mode: "edit", chat: { id: "c1", duckyStyle: "artist" } } as unknown as DuckyProfileModalMode;
  render(<DuckyProfileModal open state={edit} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Invalid skill version"));
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});
