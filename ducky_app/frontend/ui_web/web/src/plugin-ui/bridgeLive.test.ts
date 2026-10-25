// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({
  api: { plugin_live_join: vi.fn(), plugin_live_send: vi.fn(), plugin_live_status: vi.fn(), plugin_live_hold: vi.fn(),
    plugin_live_holds: vi.fn(), plugin_live_set_my_state: vi.fn(), plugin_live_member_states: vi.fn(),
    plugin_live_share: vi.fn(), plugin_live_shared: vi.fn() },
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

it("a panel sets this PC's live state as its own plugin and reads everyone's", async () => {
  host.api.plugin_live_set_my_state.mockResolvedValue({ ok: true, sent: 1 });
  host.api.plugin_live_member_states.mockResolvedValue({ ok: true, states: [{ from: { name: "Mo" }, state: { cam: [1, 2, 3] } }] });
  expect(await call("live.setMyState", { state: { cam: [0, 0, 5] } })).toMatchObject({ ok: true, result: { sent: 1 } });
  expect(host.api.plugin_live_set_my_state).toHaveBeenCalledWith("imk", { cam: [0, 0, 5] });
  await call("live.setMyState", {});  // nothing: cleared
  expect(host.api.plugin_live_set_my_state).toHaveBeenLastCalledWith("imk", null);
  expect(await call("live.setMyState", { state: [1, 2] })).toMatchObject({ ok: false });  // an object or null
  expect(await call("live.memberStates", {})).toMatchObject({ ok: true, result: { states: [{ from: { name: "Mo" } }] } });
});

it("a panel shares a component's value with the group as its own plugin and reads the group's values", async () => {
  host.api.plugin_live_share.mockResolvedValue({ ok: true });
  host.api.plugin_live_shared.mockResolvedValue({ ok: true, values: { player: { value: { playing: true }, by: { name: "Mo" } } } });
  expect(await call("live.share", { key: "player", value: { playing: true, t: 12 } })).toMatchObject({ ok: true });
  expect(host.api.plugin_live_share).toHaveBeenCalledWith("imk", "player", { playing: true, t: 12 });
  await call("live.share", { key: "player" });  // no value: dropped
  expect(host.api.plugin_live_share).toHaveBeenLastCalledWith("imk", "player", null);
  expect(await call("live.shared", {})).toMatchObject({ ok: true, result: { values: { player: { value: { playing: true } } } } });
});

it("the screen names itself for the group, and a member's own move asks only the leader, reliably", async () => {
  host.api.plugin_live_send.mockResolvedValue({ ok: true });
  await call("live.view", { v: "v1", at: "p1:video", scroll: [] });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.view", { v: "v1", at: "p1:video", scroll: [] }, "", true);
  await call("live.view", { v: "v1", at: "p1:rules", scroll: [], ask: 1, to: "d1" });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.view",
    { v: "v1", at: "p1:rules", scroll: [], ask: 1 }, "d1", false);
  await call("live.nav", { anchor: "[id=\"tab\"]", v: "v1", o: "ab12:3<x>", ask: 1, to: "d1" });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.nav",
    { anchor: "[id=\"tab\"]", v: "v1", o: "ab12:3x", ask: 1 }, "d1", false);
  await call("live.nav", { anchor: "[id=\"tab\"]", to: "d1" });  // no ask: to the group, never one PC
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.nav", { anchor: "[id=\"tab\"]" }, "", false);
});

it("pointers go fast and clamped, with an anchor no longer than 400", async () => {
  host.api.plugin_live_send.mockResolvedValue({ ok: true });
  expect(await call("live.pointer", { anchor: "x".repeat(900), fx: 3, fy: -1 })).toMatchObject({ ok: true });
  expect(host.api.plugin_live_send).toHaveBeenCalledWith("imk", "ducky.pointer", { anchor: "x".repeat(400), fx: 1, fy: 0, v: "" }, "", true);
  await call("live.select", { anchor: "[data-live-id=\"clip-3\"]", fx: 0.5 });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.select", { anchor: "[data-live-id=\"clip-3\"]" }, "", true);
  await call("live.pointer", { fx: 0.5 });
  expect(host.api.plugin_live_send).toHaveBeenCalledTimes(2);  // no anchor: nothing sent
});

it("holds go to the host's hold call, live or not; a view id keeps only safe characters", async () => {
  host.api.plugin_live_hold.mockResolvedValue({ ok: true });
  host.api.plugin_live_holds.mockResolvedValue({ ok: true, holds: [{ device: "d1", anchor: "body", t: 1, v: "v1", name: "Mo" }] });
  expect(await call("live.hold", { anchor: "[id=\"title\"]", on: true, t: 12, v: "v1<script>" })).toMatchObject({ ok: true });
  expect(host.api.plugin_live_hold).toHaveBeenCalledWith("imk", "[id=\"title\"]", true, 12, "v1script");
  await call("live.hold", { anchor: "[id=\"title\"]", on: false });
  expect(host.api.plugin_live_hold).toHaveBeenLastCalledWith("imk", "[id=\"title\"]", false, 0, "");
  expect(await call("live.hold", { on: true })).toMatchObject({ result: { ok: false } });
  expect(await call("live.holds", {})).toMatchObject({ ok: true, result: { holds: [{ name: "Mo" }] } });
});

it("a view and tab clicks go to the group: the view may drop, a tab click may not", async () => {
  host.api.plugin_live_send.mockResolvedValue({ ok: true });
  await call("live.view", { v: "v9", scroll: [{ anchor: "@doc", top: 10.4, left: 0 }, { anchor: 3 }, ...Array(10).fill({ anchor: "a", top: 1, left: 1 })] });
  const [, topic, data, , fast] = host.api.plugin_live_send.mock.calls[0];
  expect([topic, fast]).toEqual(["ducky.view", true]);
  expect((data as { scroll: unknown[] }).scroll).toHaveLength(7);  // 8 at most, the bad one dropped
  expect((data as { scroll: unknown[] }).scroll[0]).toEqual({ anchor: "@doc", top: 10, left: 0 });
  await call("live.nav", { anchor: "[id=\"video-tab\"]" });
  expect(host.api.plugin_live_send).toHaveBeenLastCalledWith("imk", "ducky.nav", { anchor: "[id=\"video-tab\"]" }, "", false);
});
