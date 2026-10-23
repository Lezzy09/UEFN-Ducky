import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentEvent } from "../types/panel";
import { shouldSpeakToolStep } from "./processNarration";
import { _resetWorkStatus, getWorkStatus, recordToolDone, recordToolStart, subscribeWorkStatus } from "./workStatus";

const enqueueProcessSpeak = vi.fn();
let eventHandler: ((event: AgentEvent) => void) | null = null;
let talk = 0.3;

vi.mock("./liveSpeakQueue", () => ({
  enqueueProcessSpeak: (...args: unknown[]) => enqueueProcessSpeak(...args),
  enqueueAnswerSpeak: vi.fn(),
  enqueueFinalSpeak: vi.fn(),
  clearLiveSpeakQueueForChat: vi.fn(),
  getCurrentSpokenLine: () => null,
  getLiveSpeakTransport: () => ({ hasPrev: false, hasNext: false, hasNewer: false, behind: 0, cursor: -1, length: 0 }),
  liveSpeakQueueLength: () => 0,
  parkLiveSpeakQueue: vi.fn(),
  subscribeLiveSpeakTransport: () => () => {},
}));
vi.mock("../hooks/useAgentEventBus", () => ({
  installAgentEventBus: () => {},
  subscribeAgentEvents: (fn: (event: AgentEvent) => void) => {
    eventHandler = fn;
    return () => {
      eventHandler = null;
    };
  },
}));
vi.mock("./voiceSettings", () => ({ getVoiceSettings: () => ({ processTalk: talk }) }));
vi.mock("./ttsEngine", () => ({ ttsEngine: { onStateChange: () => () => {}, isSpeaking: () => false } }));
vi.mock("./speakReply", () => ({
  loadLastAssistantText: async () => "",
  prepareSpokenText: async (t: string) => t,
  summarizeForSpeech: async (t: string) => t,
}));

describe("tool step gating", () => {
  it("speaks about processTalk of the steps, first one included", () => {
    const spoken = (t: number, n = 10) => Array.from({ length: n }, (_, i) => i).filter((i) => shouldSpeakToolStep(i, t));
    expect(spoken(0.3)).toEqual([0, 3, 6]);
    expect(spoken(0.3).length).toBeLessThanOrEqual(3);
    expect(spoken(1)).toHaveLength(10);
    expect(spoken(0)).toHaveLength(0);
    expect(spoken(0.7)).toHaveLength(7);
  });
});

describe("work status feed", () => {
  beforeEach(() => _resetWorkStatus());

  it("keeps one line per chat and notifies subscribers", () => {
    const seen = vi.fn();
    const off = subscribeWorkStatus(seen);
    recordToolStart("c1", { name: "workspace_read_file", arguments: { path: "voice/voiceSettings.ts" } }, 1);
    expect(getWorkStatus("c1")).toMatch(/^Reading the file .+…$/);
    recordToolDone("c1", { name: "workspace_read_file", arguments: { path: "voice/voiceSettings.ts" }, status: "done" });
    expect(getWorkStatus("c1")).toMatch(/… done\.$/);
    recordToolDone("c1", { name: "workspace_read_file", arguments: {}, status: "error" });
    expect(getWorkStatus("c1")).toMatch(/… failed\.$/);
    expect(getWorkStatus("c2")).toBe("");
    expect(seen).toHaveBeenCalledTimes(3);
    off();
  });
});

describe("live narration with the feed", () => {
  beforeEach(async () => {
    enqueueProcessSpeak.mockClear();
    eventHandler = null;
    vi.resetModules();
    const { _resetLiveSpeakService } = await import("./liveSpeakService");
    _resetLiveSpeakService();
  });

  it("a 10-tool run at talk 0.3 speaks at most 3 lines and the status follows every step", async () => {
    talk = 0.3;
    const { startLiveChat } = await import("./liveSpeakService");
    const feed = await import("./workStatus");
    startLiveChat("chat-a", { voiceId: "v", speed: 1 });
    for (let i = 0; i < 10; i += 1) {
      const tool = { name: "workspace_read_file", arguments: { path: `f${i}.ts` }, status: "done", result: "ok" };
      eventHandler!({ type: "tool", conv_id: "chat-a", tool } as AgentEvent);
      eventHandler!({ type: "tool_done", conv_id: "chat-a", tool } as AgentEvent);
      expect(feed.getWorkStatus("chat-a")).toMatch(new RegExp(`f${i} dot ts… done\\.$`, "i"));
    }
    expect(enqueueProcessSpeak.mock.calls.length).toBeLessThanOrEqual(3);
    expect(enqueueProcessSpeak.mock.calls.length).toBeGreaterThan(0);
  });

  it("starts counting again on the next turn", async () => {
    talk = 0.3;
    const { startLiveChat } = await import("./liveSpeakService");
    startLiveChat("chat-a", { voiceId: "v", speed: 1 });
    const tool = { name: "workspace_read_file", arguments: {} };
    eventHandler!({ type: "tool", conv_id: "chat-a", tool } as AgentEvent);
    eventHandler!({ type: "tool", conv_id: "chat-a", tool } as AgentEvent);
    eventHandler!({ type: "assistant_done", conv_id: "chat-a", text: "Done." } as AgentEvent);
    enqueueProcessSpeak.mockClear();
    eventHandler!({ type: "tool", conv_id: "chat-a", tool } as AgentEvent);
    expect(enqueueProcessSpeak).toHaveBeenCalledTimes(1);
  });
});
