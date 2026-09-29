// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PluginDataPanel, totalsText } from "./PluginDataPanel";
import type { PluginScopeStatus } from "../../../types/panel";

const api = vi.hoisted(() => ({
  plugin_scope_status: vi.fn(),
  plugin_scope_choices: vi.fn(),
  plugin_scope_set: vi.fn(),
  plugin_data_copy_to_team: vi.fn(),
  plugin_data_open_web: vi.fn(),
}));
vi.mock("../../../hooks/usePanelApi", () => ({ getApi: () => api }));

const LOCAL: PluginScopeStatus = {
  ok: true, visible: true, canChange: true, state: "ok",
  scope: { kind: "personal", label: "Local", teamId: "", readOnly: false },
  local: { docs: 3, files: 1, docsBytes: 1024, filesBytes: 2048 },
  current: { docs: 3, files: 1, docsBytes: 1024, filesBytes: 2048 },
};
const TEAM: PluginScopeStatus = {
  ...LOCAL, members: 4, syncedAt: null, pending: 2, teamSlug: "alpha",
  scope: { kind: "team", label: "Alpha Studio", teamId: "teamT", readOnly: false },
  current: { docs: 5, files: 0, docsBytes: 4096, filesBytes: 0 },
};

beforeEach(() => {
  api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
    { id: "personal", kind: "personal", label: "Local" },
    { id: "teamT", kind: "team", label: "Alpha Studio", members: 4, slug: "alpha" },
  ] });
  api.plugin_scope_set.mockResolvedValue({ ok: true });
  api.plugin_data_copy_to_team.mockResolvedValue({ ok: true, copied: 3, kept: 1 });
  api.plugin_data_open_web.mockResolvedValue({ ok: true });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Plugins page → Data", () => {
  it("says nothing for accounts without the Teams beta", async () => {
    api.plugin_scope_status.mockResolvedValue({ ...LOCAL, visible: false });
    const { container } = render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalledWith("brainrot-tcg"));
    expect(container.textContent).toBe("");
  });

  it("shows where the data lives and switches to a team only after confirming", async () => {
    api.plugin_scope_status.mockResolvedValue(LOCAL);
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Only on this PC, for your account.")).toBeTruthy();
    expect(screen.getByText("3 docs · 1 file · 3 KB")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Copy Local data/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keep data in…" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Team · Alpha Studio/ }));
    expect(screen.getByText(/Your Local copy stays on this PC, separate. Nothing is copied./)).toBeTruthy();
    expect(api.plugin_scope_set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("brainrot-tcg", "teamT"));
    expect(await screen.findByText("BrainRot TCG now shows Alpha Studio's copy.")).toBeTruthy();
  });

  it("copies Local data into the team one way, and opens the team's data on the web", async () => {
    api.plugin_scope_status.mockResolvedValue(TEAM);
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Every member sees and changes the same copy.")).toBeTruthy();
    expect(screen.getByText("5 docs · 0 files · 4 KB")).toBeTruthy();
    expect(screen.getByText(/2 changes waiting/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy Local data into Alpha Studio" }));
    expect(screen.getByText(/Items Alpha Studio already has are kept. Nothing goes to any other team./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(api.plugin_data_copy_to_team).toHaveBeenCalledWith("brainrot-tcg", "teamT"));
    expect(await screen.findByText(/Copied 3 items into Alpha Studio. 1 item Alpha Studio already had stayed as they were./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /View on the web/ }));
    expect(api.plugin_data_open_web).toHaveBeenCalledWith("brainrot-tcg");
  });

  it("keeps a read-only team copy from being written", async () => {
    api.plugin_scope_status.mockResolvedValue({ ...TEAM, state: "waiting", scope: { ...TEAM.scope!, readOnly: true } });
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Waiting for team data. Read-only until it arrives.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Copy Local data/ })).toBeNull();
  });

  it("words the totals", () => {
    expect(totalsText(undefined)).toBe("Nothing stored");
    expect(totalsText({ docs: 1, files: 2, docsBytes: 0, filesBytes: 1536 })).toBe("1 doc · 2 files · 1.5 KB");
  });
});
