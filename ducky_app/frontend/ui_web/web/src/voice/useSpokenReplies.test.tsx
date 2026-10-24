// @vitest-environment jsdom
import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  emit: null as null | ((event: Record<string, unknown>) => void),
  settings: { enabled: true, spokenStyle: "summary" },
  load: vi.fn(),
  speakReply: vi.fn(),
}));
vi.mock("../hooks/useAgentEventBus", () => ({
  installAgentEventBus: vi.fn(),
  subscribeAgentEvents: (fn: typeof mock.emit) => { mock.emit = fn; return () => {}; },
}));
vi.mock("./voiceSettings", () => ({
  getVoiceSettings: () => mock.settings,
  loadVoiceSettings: () => { mock.load(); return Promise.resolve(mock.settings); },
  subscribeVoiceSettings: () => () => {},
}));
vi.mock("./speakReply", () => ({ speakReply: mock.speakReply }));
vi.mock("./ttsEngine", () => ({ ttsEngine: { setVoice: vi.fn(), setRate: vi.fn(), flush: vi.fn() } }));
vi.mock("./liveChats", () => ({ getLiveVoiceChatIds: () => new Set() }));
import { noteUserTurn } from "./spokenReplyGate";
import { useSpokenReplies } from "./useSpokenReplies";

beforeEach(() => {
  mock.load.mockClear();
  mock.speakReply.mockClear();
  mock.settings = { enabled: true, spokenStyle: "summary" };
});
afterEach(cleanup);

describe("useSpokenReplies", () => {
  it("re-reads voice settings when an agent changes settings", () => {
    renderHook(() => useSpokenReplies());
    mock.load.mockClear();
    mock.emit?.({ type: "settings_changed", keys: ["voice_enabled"] });
    expect(mock.load).toHaveBeenCalledTimes(1);
  });

  it("stays quiet when spoken replies are off", () => {
    mock.settings = { enabled: false, spokenStyle: "summary" };
    renderHook(() => useSpokenReplies());
    noteUserTurn("c1");
    mock.emit?.({ type: "assistant_done", conv_id: "c1" });
    expect(mock.speakReply).not.toHaveBeenCalled();
  });

  it("speaks the reply to a turn the user sent when on", () => {
    renderHook(() => useSpokenReplies());
    noteUserTurn("c2");
    mock.emit?.({ type: "assistant_done", conv_id: "c2" });
    expect(mock.speakReply).toHaveBeenCalledWith("c2", undefined, { speed: undefined });
  });
});
