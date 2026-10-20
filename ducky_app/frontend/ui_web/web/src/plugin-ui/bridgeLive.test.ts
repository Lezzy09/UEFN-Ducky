// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({
  api: { plugin_live_join: vi.fn(), plugin_live_send: vi.fn(), plugin_live_status: vi.fn() },
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => host.api, isRemote: () => false }));

import { handleBridgeRequest } from "./bridge";
import { BRIDGE_CHANNEL } from "./constants";

afterEach(() => vi.resetAllMocks());

const ctx = { pluginId: "imk", panelId: "main", tabId: "plugin:imk:main", version: "1", iframe: null } as never;
const call = (method: string, params: Record<string, unknown>) =>
  handleBridgeRequest(ctx, { channel: BRIDGE_CHANNEL, id: "1", method, params } as never);

it("a panel goes live and sends its own topics as its own plugin, never the host's", async () => {
  host.api.plugin_live_join.mockResolvedValue({ ok: true, on: true });
  host.api.plugin_live_send.mockResolvedValue({ ok: true, sent: 2 });
  expect(await call("live.join", { room: "seq-1" })).toMatchObject({ ok: true, result: { ok: true, on: true } });
  expect(host.api.plugin_live_join).toHaveBeenCalledWith("imk", "seq-1");
  expect(await call("live.send", { topic: "playhead", data: { t: 4.2 }, to: "d1" })).toMatchObject({ ok: true });
  expect(host.api.plugin_live_send).toHaveBeenCalledWith("imk", "playhead", { t: 4.2 }, "d1", false);
  expect(await call("live.send", { topic: "ducky.change", data: {} })).toMatchObject({ ok: false });
  expect(host.api.plugin_live_send).toHaveBeenCalledTimes(1);
});

it("pointers go fast and clamped, with an anchor no longer than 400", async () => {
  host.api.plugin_live_send.mockResolvedValue({ ok: true });
  expect(await call("live.pointer", { anchor: "x".repeat(900), fx: 3, fy: -1 })).toMatchObject({ ok: true });
  expect(host.api.plugin_live_send).toHaveBeenCalledWith("imk", "ducky.pointer", { anchor: "x".repeat(400), fx: 1, fy: 0 }, "", true);
  await call("live.select", { anchor: "[data-live-id=\"clip-3\"]", fx: 0.5 });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.select", { anchor: "[data-live-id=\"clip-3\"]" }, "", true);
  await call("live.pointer", { fx: 0.5 });
  expect(host.api.plugin_live_send).toHaveBeenCalledTimes(2);  // no anchor: nothing sent
});
