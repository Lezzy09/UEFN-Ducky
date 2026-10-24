// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => null, isRemoteDuckyWindow: () => false }));

import { callOverHttp } from "./panelHttp";
import { getApi } from "./usePanelApi";

const fetchMock = vi.fn();
const bridge = { get_listener_status: vi.fn(), get_skill_info: vi.fn(), list_folders: vi.fn() };

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  (window as unknown as { pywebview: unknown }).pywebview = { api: bridge };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  delete (window as unknown as { pywebview?: unknown }).pywebview;
});

it("callOverHttp posts the args to /__panel_api and returns the result", async () => {
  fetchMock.mockResolvedValue(reply(200, { ok: true, result: { packs: 3 } }));
  await expect(callOverHttp("get_skill_info", ["a", 1])).resolves.toEqual({ ok: true, result: { packs: 3 } });
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/__panel_api/get_skill_info");
  expect(JSON.parse(String(init.body))).toEqual({ args: ["a", 1] });
});

it("callOverHttp reports a 500 or a thrown method as a failure", async () => {
  fetchMock.mockResolvedValueOnce(reply(500, {}));
  await expect(callOverHttp("get_plan", [])).resolves.toEqual({ ok: false, timedOut: false });
  fetchMock.mockResolvedValueOnce(reply(200, { ok: false, error: "boom" }));
  await expect(callOverHttp("get_plan", [])).resolves.toEqual({ ok: false, timedOut: false });
});

it("a routed method through getApi() goes over HTTP, and to the bridge on a 500", async () => {
  // jsdom serves the page over http://, like the desktop window's local server.
  const api = getApi()!;
  expect(getApi()).toBe(api);
  fetchMock.mockResolvedValueOnce(reply(200, { ok: true, result: "over-http" }));
  await expect(api.get_skill_info()).resolves.toBe("over-http");
  expect(bridge.get_skill_info).not.toHaveBeenCalled();

  fetchMock.mockResolvedValueOnce(reply(500, {}));
  bridge.get_skill_info.mockResolvedValue("over-bridge");
  await expect(api.get_skill_info()).resolves.toBe("over-bridge");
});

it("a method that is not routed stays on the bridge", async () => {
  bridge.list_folders.mockResolvedValue(["f"]);
  await expect(getApi()!.list_folders()).resolves.toEqual(["f"]);
  expect(fetchMock).not.toHaveBeenCalled();
});
