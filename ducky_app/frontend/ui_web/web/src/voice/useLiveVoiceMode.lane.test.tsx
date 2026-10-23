// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLiveVoiceChat } from "./liveChats";

const mock = vi.hoisted(() => ({
  handlers: {} as Record<string, (...args: any[]) => void>,
  tts: [] as ((s: string) => void)[],
  laneTurn: vi.fn(),
  cancel: vi.fn(),
  speak: vi.fn(),
}));
vi.mock("../hooks/usePanelApi", () => ({
  getApi: () => ({ voice_lane_turn: mock.laneTurn, cancel_agent: mock.cancel }),
}));
vi.mock("./transcriptionSession", () => ({
  prewarmSpeech: vi.fn(),
  createStreamingTranscriptionSession: () => ({
    start: async (h: typeof mock.handlers) => { mock.handlers = h; },
    abort: vi.fn(),
  }),
}));
vi.mock("./liveSpeakService", () => ({
  claimMic: () => true, releaseMic: vi.fn(), interruptLiveSpeak: vi.fn(),
  isLiveChat: () => true, updateLiveChatVoice: vi.fn(), speakLiveReply: mock.speak,
}));
vi.mock("./liveSpeakQueue", () => ({
  getCurrentSpokenLine: () => null, getLiveSpeakTransport: () => ({}),
  liveSpeakQueueLength: () => 0, speakNewest: vi.fn(), speakNext: vi.fn(), speakPrev: vi.fn(),
  subscribeLiveSpeakTransport: () => () => {},
}));
vi.mock("./ttsEngine", () => ({
  ttsEngine: {
    isSpeaking: () => false, setVoice: vi.fn(), setRate: vi.fn(),
    onStateChange: (f: (s: string) => void) => { mock.tts.push(f); return () => {}; },
  },
}));
vi.mock("./voiceSettings", () => ({
  getVoiceSettings: () => ({ sttProvider: "", defaultVoice: "", liveAutoSend: true }),
  resolveVoiceId: () => "", resolveSpeed: () => 1, subscribeVoiceSettings: () => () => {},
  resolveVoiceModel: () => "claude_code:claude-haiku-5-5",
}));
import { _resetLiveLatency, getLiveLatencySamples } from "./liveLatency";
import { useLiveVoiceMode } from "./useLiveVoiceMode";

const base = { enabled: true, chatId: "live", muted: false, onInterim: vi.fn() };

beforeEach(() => {
  vi.useFakeTimers();
  mock.laneTurn.mockReset();
  mock.cancel.mockReset();
  mock.speak.mockReset();
  mock.tts = [];
  _resetLiveLatency();
  setLiveVoiceChat("live", true);
  vi.spyOn(console, "info").mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

async function speakTurn(words: string) {
  await act(async () => {});
  act(() => mock.handlers.onFinal(words));
  await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
}

describe("live turns go to the voice lane first", () => {
  it("answer only: speaks right away, no message to the chat", async () => {
    mock.laneTurn.mockResolvedValue({ ok: true, action: "answer", text: "Compiling, 2 errors left." });
    const onTranscript = vi.fn();
    const onTurnEnd = vi.fn();
    renderHook(() => useLiveVoiceMode({ ...base, agentRunning: true, onTranscript, onTurnEnd }));
    await speakTurn("what are you doing?");
    expect(mock.laneTurn).toHaveBeenCalledWith("live", "what are you doing?", "", true, "claude_code:claude-haiku-5-5");
    expect(mock.speak).toHaveBeenCalledWith("live", "Compiling, 2 errors left.");
    expect(onTranscript).not.toHaveBeenCalled();
    expect(onTurnEnd).not.toHaveBeenCalled();
    act(() => mock.tts.forEach((f) => f("speaking")));
    expect(getLiveLatencySamples()[0]?.lane).toBe("voice lane");
  });

  it("hand to agent: the whole turn is sent as one message", async () => {
    mock.laneTurn.mockResolvedValue({ ok: true, action: "agent", text: "On it." });
    const onTranscript = vi.fn();
    const onTurnEnd = vi.fn();
    renderHook(() => useLiveVoiceMode({ ...base, agentRunning: false, onTranscript, onTurnEnd }));
    await speakTurn("make the door blue");
    expect(mock.speak).toHaveBeenCalledWith("live", "On it.");
    expect(onTranscript).toHaveBeenCalledWith("make the door blue");
    expect(onTurnEnd).toHaveBeenCalledTimes(1);
  });

  it("'stop' cancels the running agent", async () => {
    const onTurnEnd = vi.fn();
    renderHook(() => useLiveVoiceMode({ ...base, agentRunning: true, onTranscript: vi.fn(), onTurnEnd }));
    await speakTurn("stop");
    expect(mock.cancel).toHaveBeenCalledWith("live");
    expect(mock.laneTurn).not.toHaveBeenCalled();
    expect(onTurnEnd).not.toHaveBeenCalled();
  });
});
