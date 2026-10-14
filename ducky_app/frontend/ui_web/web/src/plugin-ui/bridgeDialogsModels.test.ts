// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({
  api: { get_models_catalog: vi.fn(), pick_workflow_folder: vi.fn() },
  confirm: vi.fn(),
  alert: vi.fn(),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => host.api, isRemote: () => false }));
vi.mock("../contexts/ConfirmModalContext", () => ({ confirmFromHost: host.confirm, alertFromHost: host.alert }));

import { handleBridgeRequest } from "./bridge";
import { BRIDGE_CHANNEL } from "./constants";

afterEach(() => {
  vi.resetAllMocks();
});

const ctx = { pluginId: "island-media-kit", panelId: "main", tabId: "plugin:imk:main", version: "1", iframe: null } as never;
const call = (method: string, params: Record<string, unknown>) =>
  handleBridgeRequest(ctx, { channel: BRIDGE_CHANNEL, id: "1", method, params } as never);

it("opens Ducky's own confirm modal for a plugin's question and returns the answer", async () => {
  host.confirm.mockResolvedValue(true);
  const res = await call("ui.confirm", { message: "Remove variant B?", danger: true });
  expect(host.confirm).toHaveBeenCalledWith(expect.objectContaining({ message: "Remove variant B?", danger: true }));
  expect(res).toMatchObject({ ok: true, result: { confirmed: true } });
});

it("treats a cancelled or extra-button answer as not confirmed", async () => {
  host.confirm.mockResolvedValue("extra");
  expect(await call("ui.confirm", { message: "Delete?" })).toMatchObject({ ok: true, result: { confirmed: false } });
});

it("refuses an empty question", async () => {
  expect(await call("ui.confirm", { message: "  " })).toMatchObject({ ok: false });
  expect(host.confirm).not.toHaveBeenCalled();
});

it("lists the chat models a plugin can pass to llm.complete, without keys or prices", async () => {
  host.api.get_models_catalog.mockResolvedValue({
    default_model: "m-default",
    agent_model: "m-agent",
    models: [{ id: "m1", name: "Model One", provider: "openai", price_in: 3, is_local: false }],
  });
  const res = await call("models.list", {});
  expect(res).toMatchObject({ ok: true, result: { default_model: "m-agent", models: [{ id: "m1", name: "Model One", provider: "openai", is_local: false }] } });
  expect(JSON.stringify(res)).not.toContain("price_in");
});

it("opens the Windows folder picker and returns the chosen folder", async () => {
  host.api.pick_workflow_folder.mockResolvedValue({ ok: true, folder: "D:/Trailers" });
  expect(await call("files.pickFolder", {})).toMatchObject({ ok: true, result: { folder: "D:/Trailers" } });
  host.api.pick_workflow_folder.mockResolvedValue({ ok: true, folder: "" });
  expect(await call("files.pickFolder", {})).toMatchObject({ ok: true, result: { folder: "" } });
});
