// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

const api: { remote_deny_methods?: () => unknown } = {};
vi.mock("../hooks/usePanelApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../hooks/usePanelApi")>()),
  getApi: () => api,
}));

import { DENY_WAIT_MS, deniedMethods, forgetDeniedMethodsForTest } from "./directPeer";

describe("deniedMethods", () => {
  afterEach(() => {
    forgetDeniedMethodsForTest();
    vi.useRealTimers();
  });

  it("gives up on a reply that never comes and asks again next time", async () => {
    vi.useFakeTimers();
    api.remote_deny_methods = () => new Promise(() => {});
    const first = deniedMethods();
    await vi.advanceTimersByTimeAsync(DENY_WAIT_MS);
    expect(await first).toBeNull();
    api.remote_deny_methods = () => Promise.resolve(["set_uefn_plugin_secret"]);
    expect(await deniedMethods()).toEqual(new Set(["set_uefn_plugin_secret"]));
  });

  it("keeps the list once Ducky has answered", async () => {
    let asks = 0;
    api.remote_deny_methods = () => {
      asks += 1;
      return Promise.resolve(["test_key"]);
    };
    await deniedMethods();
    await deniedMethods();
    expect(asks).toBe(1);
  });

  it("fails closed when Ducky gives no list", async () => {
    api.remote_deny_methods = undefined;
    expect(await deniedMethods()).toBeNull();
  });
});
