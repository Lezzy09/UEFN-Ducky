// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { DirectTransport, directConfigFromLocation, hideDesktopBridge, isDirectMode, isRemoteDuckyWindow } from "./directTransport";

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

describe("pictures asked for while the link is still opening", () => {
  type FakeChannel = {
    readyState: string;
    sent: string[];
    send(s: string): void;
    onopen: null | (() => void);
    onmessage: null | ((ev: { data: string | ArrayBuffer }) => void);
  };
  function linkWithBlob(readyState: string) {
    const ch: FakeChannel = {
      readyState,
      sent: [],
      send(s) { this.sent.push(s); },
      onopen: null,
      onmessage: null,
    };
    const t = new DirectTransport({ bridge: "local", desktopOrigin: "", panelVersion: "1" });
    const inner = t as unknown as { blob: FakeChannel; wireChannels(): void };
    inner.blob = ch;
    inner.wireChannels();
    return { t, ch };
  }
  function answer(ch: FakeChannel, id: number, bytes: number[]) {
    ch.onmessage?.({ data: JSON.stringify({ id, status: 200, type: "image/png", size: bytes.length }) });
    const frame = new Uint8Array(4 + bytes.length);
    new DataView(frame.buffer).setUint32(0, id);
    frame.set(bytes, 4);
    ch.onmessage?.({ data: frame.buffer });
    ch.onmessage?.({ data: JSON.stringify({ id, done: true }) });
  }

  it("wait for the blob channel and load once it opens (they used to stay broken)", async () => {
    const { t, ch } = linkWithBlob("connecting");
    const got = t.fetchBlob("/duckies/Artist.png");
    expect(ch.sent).toEqual([]);
    ch.readyState = "open";
    ch.onopen?.();
    const asked = JSON.parse(ch.sent[0]) as { id: number; get: string };
    expect(asked.get).toBe("/duckies/Artist.png");
    answer(ch, asked.id, [1, 2, 3]);
    const res = await got;
    expect(res.status).toBe(200);
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("go out at once when the link is already up", () => {
    const { t, ch } = linkWithBlob("open");
    void t.fetchBlob("/plugin-ui/forge/icon.png");
    expect(JSON.parse(ch.sent[0])).toMatchObject({ get: "/plugin-ui/forge/icon.png" });
  });
});
