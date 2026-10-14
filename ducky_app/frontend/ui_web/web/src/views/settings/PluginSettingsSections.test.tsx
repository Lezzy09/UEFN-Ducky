// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const pluginCall = vi.fn();
let api: Record<string, unknown> = {};
let sections: unknown[] = [];
vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../../hooks/usePluginContributions", async (importActual) => {
  const actual = await importActual<typeof import("../../hooks/usePluginContributions")>();
  return { ...actual, usePluginContributions: () => ({ settings_sections: sections }) };
});
vi.mock("../../hooks/usePluginUiPrefs", () => ({
  usePluginUiPrefs: () => ({ prefs: {}, setPref: vi.fn(), setPrefs: vi.fn(), getBool: () => false }),
}));
vi.mock("./PluginWalkthroughReplayButton", () => ({ PluginWalkthroughReplayButton: () => null }));
const { PluginSettingsSections } = await import("./PluginSettingsSections");

const account = {
  id: "account",
  tab: "Notion",
  plugin_id: "notion",
  title: "Notion account",
  order: 10,
  properties: [
    {
      id: "account",
      type: "action",
      label: "Sign in with Notion",
      rpc: "connect",
      status_rpc: "status",
      connected_label: "Disconnect",
      connected_rpc: "disconnect",
    },
  ],
};

beforeEach(() => {
  pluginCall.mockReset();
  api = { plugin_call: pluginCall };
  sections = [account];
});
afterEach(cleanup);

it("reads the status on mount, signs in, then offers to disconnect", async () => {
  pluginCall.mockImplementation(async (_pid: string, method: string) =>
    method === "status"
      ? { ok: true, connected: false, detail: "Not connected" }
      : { ok: true, connected: true, detail: "Connected to Studio" },
  );
  render(<PluginSettingsSections tabId="Notion" />);
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Not connected"));
  expect(pluginCall).toHaveBeenCalledWith("notion", "status", {});

  fireEvent.click(screen.getByRole("button", { name: "Sign in with Notion" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Connected to Studio"));
  expect(pluginCall).toHaveBeenCalledWith("notion", "connect", {});

  pluginCall.mockResolvedValue({ ok: true, connected: false, detail: "Not connected" });
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign in with Notion" })).toBeTruthy());
  expect(pluginCall).toHaveBeenLastCalledWith("notion", "disconnect", {});
});

it("shows a failed sign-in as an error and keeps the sign-in button", async () => {
  pluginCall.mockImplementation(async (_pid: string, method: string) =>
    method === "status"
      ? { ok: true, connected: false, detail: "Not connected" }
      : { ok: false, connected: false, detail: "Notion sign-in timed out" },
  );
  render(<PluginSettingsSections tabId="Notion" />);
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Not connected"));
  fireEvent.click(screen.getByRole("button", { name: "Sign in with Notion" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Notion sign-in timed out"));
  expect(screen.getByRole("status").className).toContain("is-error");
  expect(screen.getByRole("button", { name: "Sign in with Notion" })).toBeTruthy();
});

it("asks for an app update when the bridge has no plugin_call", async () => {
  api = {};
  render(<PluginSettingsSections tabId="Notion" />);
  await waitFor(() =>
    expect(screen.getByRole("status").textContent).toBe("Update the app to use this button"),
  );
});
