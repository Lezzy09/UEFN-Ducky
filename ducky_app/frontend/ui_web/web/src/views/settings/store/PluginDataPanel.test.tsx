// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render as renderPlain, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { ConfirmModalProvider } from "../../../contexts/ConfirmModalContext";
import { PluginDataPanel, totalsText } from "./PluginDataPanel";
import type { PluginScopeStatus } from "../../../types/panel";

const api = vi.hoisted(() => ({
  plugin_scope_status: vi.fn(),
  plugin_scope_choices: vi.fn(),
  plugin_scope_set: vi.fn(),
  plugin_data_copy_to_space: vi.fn(),
  plugin_data_open_web: vi.fn(),
  plugin_scope_unlock: vi.fn(),
}));
vi.mock("../../../hooks/usePanelApi", () => ({ getApi: () => api }));

const render = (ui: ReactElement) => renderPlain(<ConfirmModalProvider>{ui}</ConfirmModalProvider>);

const LOCAL: PluginScopeStatus = {
  ok: true, visible: true, canChange: true, state: "ok",
  scope: { kind: "personal", label: "Local", spaceId: "", readOnly: false },
  local: { docs: 3, files: 1, docsBytes: 1024, filesBytes: 2048 },
  current: { docs: 3, files: 1, docsBytes: 1024, filesBytes: 2048 },
};
const SHARED: PluginScopeStatus = {
  ...LOCAL, members: 4, syncedAt: null, pending: 2, webPage: true,
  scope: { kind: "shared", label: "Alpha Studio", spaceId: "spaceT", readOnly: false },
  current: { docs: 5, files: 0, docsBytes: 4096, filesBytes: 0 },
};

beforeEach(() => {
  api.plugin_scope_choices.mockResolvedValue({ ok: true, choices: [
    { id: "personal", kind: "personal", label: "Local" },
    { id: "spaceT", kind: "shared", label: "Alpha Studio", members: 4, slug: "alpha" },
  ] });
  api.plugin_scope_set.mockResolvedValue({ ok: true });
  api.plugin_data_copy_to_space.mockResolvedValue({ ok: true, copied: 3, kept: 1 });
  api.plugin_data_open_web.mockResolvedValue({ ok: true });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Plugins page → Data", () => {
  it("says nothing while the account has no shared spaces", async () => {
    api.plugin_scope_status.mockResolvedValue({ ...LOCAL, visible: false });
    const { container } = render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalledWith("brainrot-tcg"));
    expect(container.textContent).toBe("");
  });

  it("shows where the data lives and switches to a space only after confirming", async () => {
    api.plugin_scope_status.mockResolvedValue(LOCAL);
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Only on this PC, for your account.")).toBeTruthy();
    expect(screen.getByText("3 docs · 1 file · 3 KB")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Copy Local data/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keep data in…" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Space · Alpha Studio/ }));
    expect(screen.getByText(/Your Local copy stays on this PC, separate. Nothing is copied./)).toBeTruthy();
    expect(api.plugin_scope_set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(api.plugin_scope_set).toHaveBeenCalledWith("brainrot-tcg", "spaceT"));
    expect(await screen.findByText("BrainRot TCG now shows Alpha Studio's copy.")).toBeTruthy();
  });

  it("copies Local data into the space one way, and opens the space's data on the web", async () => {
    api.plugin_scope_status.mockResolvedValue(SHARED);
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Every member sees and changes the same copy.")).toBeTruthy();
    expect(screen.getByText("5 docs · 0 files · 4 KB")).toBeTruthy();
    expect(screen.getByText(/2 changes waiting/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy Local data into Alpha Studio" }));
    expect(screen.getByText(/Items Alpha Studio already has are kept. Nothing goes to any other space./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(api.plugin_data_copy_to_space).toHaveBeenCalledWith("brainrot-tcg", "spaceT"));
    expect(await screen.findByText(/Copied 3 items into Alpha Studio. 1 item Alpha Studio already had stayed as they were./)).toBeTruthy();
    api.plugin_data_copy_to_space.mockResolvedValue({ ok: true, copied: 0, kept: 0, tooBig: ["scene.big"] });
    fireEvent.click(screen.getByRole("button", { name: "Copy Local data into Alpha Studio" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText("Copied 0 items into Alpha Studio. 1 too big to share stayed Local.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /View on the web/ }));
    expect(api.plugin_data_open_web).toHaveBeenCalledWith("brainrot-tcg");
  });

  it("shows no Data section for a plugin that can't share", async () => {
    api.plugin_scope_status.mockResolvedValue({ ...LOCAL, shareable: false });
    const { container } = render(<PluginDataPanel pluginId="scene-maker" name="Scene Maker" />);
    await waitFor(() => expect(api.plugin_scope_status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
    expect(screen.queryByRole("button", { name: "Keep data in…" })).toBeNull();
  });

  it("keeps a read-only shared copy from being written", async () => {
    api.plugin_scope_status.mockResolvedValue({ ...SHARED, state: "waiting", scope: { ...SHARED.scope!, readOnly: true } });
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Waiting for space data. Read-only until it arrives.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Copy Local data/ })).toBeNull();
  });

  it("a shared copy shows the scope bar's drawer, and its actions work here too", async () => {
    api.plugin_scope_unlock.mockResolvedValue({ ok: true });
    api.plugin_scope_status.mockResolvedValue({
      ...SHARED, head: 4, locks: [{ unit: "doc:deck", name: "deck", mine: true }],
      changes: { outgoing: [{ kind: "doc", key: "deck", state: "queued" }] },
    });
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    const drawer = await screen.findByRole("region", { name: "Sync details: Alpha Studio" });
    expect(within(drawer).getByText("Queued")).toBeTruthy();
    fireEvent.click(within(drawer).getByRole("button", { name: "Release deck" }));
    await waitFor(() => expect(api.plugin_scope_unlock).toHaveBeenCalledWith("brainrot-tcg", "doc:deck"));
    // The panel re-reads its status after the action.
    await waitFor(() => expect(api.plugin_scope_status.mock.calls.length).toBeGreaterThan(1));
  });

  it("a Local copy has no drawer", async () => {
    api.plugin_scope_status.mockResolvedValue(LOCAL);
    render(<PluginDataPanel pluginId="brainrot-tcg" name="BrainRot TCG" />);
    expect(await screen.findByText("Only on this PC, for your account.")).toBeTruthy();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("words the totals", () => {
    expect(totalsText(undefined)).toBe("Nothing stored");
    expect(totalsText({ docs: 1, files: 2, docsBytes: 0, filesBytes: 1536 })).toBe("1 doc · 2 files · 1.5 KB");
  });
});
