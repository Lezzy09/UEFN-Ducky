// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const host = vi.hoisted(() => ({ remote: false, api: { pick_workflow_files: vi.fn() } }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => host.api, isRemote: () => host.remote }));

import { handleBridgeRequest } from "./bridge";
import { BRIDGE_CHANNEL } from "./constants";

afterEach(() => {
  vi.resetAllMocks();
  host.remote = false;
});

const ctx = { pluginId: "imk", panelId: "main", tabId: "plugin:imk:main", version: "1", iframe: null } as never;
const pick = (params: Record<string, unknown>) =>
  handleBridgeRequest(ctx, { channel: BRIDGE_CHANNEL, id: "1", method: "files.pick", params } as never);

it("hands a panel the picked file's path and stream link, never its bytes", async () => {
  // Oct 11 2026: a 7 GB video uploaded through plugin.call in chunks froze the app.
  host.api.pick_workflow_files.mockResolvedValue({
    ok: true,
    files: [{ kind: "video", path: "D:/clips/big.mov", name: "big.mov", url: "http://127.0.0.1:4199/workflow-media/s/t/big.mov" }],
  });
  const res = await pick({ accept: "video" });
  expect(host.api.pick_workflow_files).toHaveBeenCalledWith("video", false);
  expect(res).toMatchObject({ ok: true, result: { files: [{ path: "D:/clips/big.mov", name: "big.mov" }] } });
});

it("says no on a phone, where the picker would open on the PC", async () => {
  host.remote = true;
  const res = await pick({});
  expect(res).toMatchObject({ ok: false });
  expect(host.api.pick_workflow_files).not.toHaveBeenCalled();
});
