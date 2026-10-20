// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ rtc_reply: vi.fn(), rtc_event: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
vi.mock("../hooks/useAgentEventBus", () => ({ installAgentEventBus: () => {}, subscribeAgentEventsImmediate: () => () => {} }));
vi.mock("../hooks/onApiReady", () => ({ onApiReady: (fn: () => void) => { fn(); return () => {}; } }));
vi.mock("../tabs/tabRegistryClient", () => ({ WINDOW_ID: "main" }));

import { handleRtcCmd, installLivePeerHost, livePeerCountForTest } from "./peerHost";

class FakeChannel {
  readyState = "connecting";
  sent: string[] = [];
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public label: string, public options: Record<string, unknown> = {}) {}
  send(data: string) { this.sent.push(data); }
  open() { this.readyState = "open"; this.onopen?.(); }
}

class FakePc {
  static made: FakePc[] = [];
  connectionState = "new";
  iceGatheringState = "new";
  localDescription: { type: string; sdp: string } | null = null;
  remote: unknown = null;
  channels: FakeChannel[] = [];
  closed = false;
  onconnectionstatechange: (() => void) | null = null;
  ondatachannel: ((ev: { channel: FakeChannel }) => void) | null = null;
  private listeners: (() => void)[] = [];
  constructor(public config: Record<string, unknown>) { FakePc.made.push(this); }
  createDataChannel(label: string, options: Record<string, unknown>) {
    const ch = new FakeChannel(label, options);
    this.channels.push(ch);
    return ch;
  }
  async createOffer() { return { type: "offer", sdp: "v=0 offer" }; }
  async createAnswer() { return { type: "answer", sdp: "v=0 answer" }; }
  async setLocalDescription(d: { type: string; sdp: string }) {
    this.localDescription = { type: d.type, sdp: `${d.sdp} +candidates` };
    // Gathering ends a moment later: the description waits for it.
    setTimeout(() => { this.iceGatheringState = "complete"; this.listeners.forEach((fn) => fn()); }, 5);
  }
  async setRemoteDescription(d: unknown) { this.remote = d; }
  addEventListener(_: string, fn: () => void) { this.listeners.push(fn); }
  removeEventListener(_: string, fn: () => void) { this.listeners = this.listeners.filter((f) => f !== fn); }
  close() { this.closed = true; }
}

beforeEach(() => {
  FakePc.made = [];
  vi.stubGlobal("RTCPeerConnection", FakePc);
});
afterEach(async () => {
  await handleRtcCmd({ type: "rtc_cmd", op: "close", peer: "a" });
  await handleRtcCmd({ type: "rtc_cmd", op: "close", peer: "b" });
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the main window's live links", () => {
  it("an offer carries every candidate and two channels: live (ordered) and live-fast (no retransmits)", async () => {
    await handleRtcCmd({ type: "rtc_cmd", id: "r1", op: "open", peer: "a", ice: [{ urls: "stun:x" }] });
    const pc = FakePc.made[0];
    expect(pc.config).toEqual({ iceServers: [{ urls: "stun:x" }] });
    expect(pc.channels.map((c) => [c.label, c.options])).toEqual([
      ["live", { ordered: true }], ["live-fast", { ordered: false, maxRetransmits: 0 }],
    ]);
    expect(api.rtc_reply).toHaveBeenCalledWith("r1", { offer: { type: "offer", sdp: "v=0 offer +candidates" } });
  });

  it("answers an offer, finishes with the answer, and says connected once live opens", async () => {
    await handleRtcCmd({ type: "rtc_cmd", id: "r2", op: "accept", peer: "b", offer: { type: "offer", sdp: "theirs" } });
    const pc = FakePc.made[0];
    expect(pc.remote).toEqual({ type: "offer", sdp: "theirs" });
    expect(api.rtc_reply).toHaveBeenCalledWith("r2", { answer: { type: "answer", sdp: "v=0 answer +candidates" } });
    const ch = new FakeChannel("live");
    pc.ondatachannel?.({ channel: ch });
    pc.ondatachannel?.({ channel: new FakeChannel("other") });  // not ours: ignored
    ch.open();
    expect(api.rtc_event).toHaveBeenCalledWith("b", "state", { state: "connected" });
    ch.onmessage?.({ data: "aGk=" });
    ch.onmessage?.({ data: new ArrayBuffer(2) });  // only text frames
    expect(api.rtc_event).toHaveBeenCalledWith("b", "message", { channel: "live", data: "aGk=" });
    expect(api.rtc_event).toHaveBeenCalledTimes(2);
    await handleRtcCmd({ type: "rtc_cmd", op: "send", peer: "b", channel: "live", data: "eW8=" });
    expect(ch.sent).toEqual(["eW8="]);
  });

  it("finish without an open link says so; a link reopened replaces the old one", async () => {
    await handleRtcCmd({ type: "rtc_cmd", id: "r3", op: "finish", peer: "a", answer: { type: "answer", sdp: "x" } });
    expect(api.rtc_reply).toHaveBeenCalledWith("r3", { error: "no such peer" });
    await handleRtcCmd({ type: "rtc_cmd", id: "r4", op: "open", peer: "a" });
    await handleRtcCmd({ type: "rtc_cmd", id: "r5", op: "open", peer: "a" });
    expect(FakePc.made[0].closed).toBe(true);
    expect(livePeerCountForTest()).toBe(1);
    await handleRtcCmd({ type: "rtc_cmd", id: "r6", op: "finish", peer: "a", answer: { type: "answer", sdp: "x" } });
    expect(FakePc.made[1].remote).toEqual({ type: "answer", sdp: "x" });
    expect(api.rtc_reply).toHaveBeenCalledWith("r6", { ok: true });
  });

  it("a send on a link that isn't open is dropped; close ends it and says closed", async () => {
    await handleRtcCmd({ type: "rtc_cmd", id: "r7", op: "open", peer: "a" });
    const live = FakePc.made[0].channels[0];
    await handleRtcCmd({ type: "rtc_cmd", op: "send", peer: "a", channel: "live", data: "eA==" });
    expect(live.sent).toEqual([]);
    await handleRtcCmd({ type: "rtc_cmd", op: "close", peer: "a" });
    expect(FakePc.made[0].closed).toBe(true);
    expect(api.rtc_event).toHaveBeenCalledWith("a", "state", { state: "closed" });
    expect(livePeerCountForTest()).toBe(0);
  });

  it("installs once", () => {
    const undo = installLivePeerHost();
    expect(installLivePeerHost()).not.toBe(undo);
    undo();
  });
});
