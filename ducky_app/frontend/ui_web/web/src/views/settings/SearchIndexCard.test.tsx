// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SearchStatus } from "../../types/panel";

const searchStatus = vi.fn();
const searchRebuild = vi.fn();

vi.mock("../../hooks/usePanelApi", () => ({
  getApi: () => ({ search_status: searchStatus, search_rebuild: searchRebuild }),
}));
vi.mock("../../hooks/onApiReady", () => ({ onApiReady: (fn: () => void) => (fn(), () => {}) }));
vi.mock("../../contexts/ConfirmModalContext", () => ({
  useConfirmModal: () => ({ confirm: async () => true, alert: async () => {} }),
}));
vi.mock("../../ui-targets/registry", () => ({ useUiTarget: () => ({ current: null }) }));

const { SearchIndexCard } = await import("./AppDataDatabase");

function status(partial: Partial<SearchStatus> = {}): SearchStatus {
  return {
    ok: true,
    running: false,
    model: "potion-base-8M@bf8b0566",
    model_error: "",
    docs: { pack: 123, subskill: 545, section: 2410, tool: 1257 },
    vectors: { "potion-base-8M@bf8b0566": 4335 },
    last_indexed: Date.now() / 1000 - 30,
    sources: 124,
    ...partial,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SearchIndexCard", () => {
  it("shows what is indexed and the model", async () => {
    searchStatus.mockResolvedValue(status());
    render(<SearchIndexCard refreshKey={0} />);
    await waitFor(() => expect(screen.getByText(/123 skill packs · 545 skill files · 2,410 sections · 1,257 tools/)).toBeTruthy());
    expect(screen.getByText(/meaning model potion-base-8M@bf8b0566/)).toBeTruthy();
  });

  it("says keywords only when the model is missing", async () => {
    searchStatus.mockResolvedValue(status({ model: "", model_error: "no model folder" }));
    render(<SearchIndexCard refreshKey={0} />);
    await waitFor(() => expect(screen.getByText(/keywords only \(no model folder\)/)).toBeTruthy());
  });

  it("rebuilds on request", async () => {
    searchStatus.mockResolvedValue(status());
    searchRebuild.mockResolvedValue({ ok: true });
    render(<SearchIndexCard refreshKey={0} />);
    const button = await screen.findByRole("button", { name: "Rebuild index" });
    fireEvent.click(button);
    await waitFor(() => expect(searchRebuild).toHaveBeenCalledTimes(1));
  });
});
