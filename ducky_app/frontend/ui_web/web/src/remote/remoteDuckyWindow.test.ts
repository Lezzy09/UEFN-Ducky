// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { directConfigFromLocation, hideDesktopBridge, isDirectMode, isRemoteDuckyWindow } from "./directTransport";

function at(search: string) {
  window.history.replaceState(null, "", `/remote-ducky/${search}`);
}

afterEach(() => window.history.replaceState(null, "", "/"));

describe("a window showing another of your UEFN Duckies", () => {
  it("is a direct-mode page whose handshake goes through this Ducky to that one", () => {
    at("?direct=ducky&to=key_2&name=Laptop%20Ducky");
    expect(isDirectMode()).toBe(true);
    expect(isRemoteDuckyWindow()).toBe(true);
    expect(directConfigFromLocation("1.2.3")).toEqual({ bridge: "ducky", to: "key_2", name: "Laptop Ducky", panelVersion: "1.2.3" });
  });

  it("is not the phone panel, the local test page or this Ducky's own window", () => {
    at("?direct=1");
    expect(isRemoteDuckyWindow()).toBe(false);
    expect(directConfigFromLocation("1").bridge).toBe("parent");
    at("?direct=local");
    expect(isRemoteDuckyWindow()).toBe(false);
    at("");
    expect(isDirectMode()).toBe(false);
    expect(isRemoteDuckyWindow()).toBe(false);
  });

  it("never gets this Ducky's JS bridge, even when pywebview assigns one later", () => {
    hideDesktopBridge();
    (window as Window & { pywebview?: unknown }).pywebview = { api: {} };
    expect((window as Window & { pywebview?: unknown }).pywebview).toBeUndefined();
  });
});
