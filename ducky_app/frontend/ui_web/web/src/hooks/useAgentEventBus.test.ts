// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "../types/panel";
import {
  coalesceAgentEvents,
  nextEventPollRetryMs,
  pushLocalAgentEvent,
  remoteGoneIsLive,
  replayedCount,
  subscribeAgentEventsImmediate,
} from "./useAgentEventBus";

describe("nextEventPollRetryMs", () => {
  it("doubles from 500ms and caps at 8s", () => {
    expect(nextEventPollRetryMs(500)).toBe(1000);
    expect(nextEventPollRetryMs(4000)).toBe(8000);
    expect(nextEventPollRetryMs(8000)).toBe(8000);
  });
});

describe("remoteGoneIsLive", () => {
  it("ignores remote_gone on catch-up and kicks only after the poller is live", () => {
    expect(remoteGoneIsLive(false, "remote_gone")).toBe(false);
    expect(remoteGoneIsLive(true, "remote_gone")).toBe(true);
    expect(remoteGoneIsLive(true, "text_delta")).toBe(false);
  });

  it("does not treat HTTP 403 as a kick (cookie flakes retry)", () => {
    expect(remoteGoneIsLive(true, "forbidden")).toBe(false);
    expect(remoteGoneIsLive(true, "403")).toBe(false);
  });
});

describe("coalesceAgentEvents", () => {
  it("joins adjacent high-frequency deltas without crossing tool boundaries", () => {
    const events: AgentEvent[] = [
      { type: "thinking", text: "one ", conv_id: "c", run_id: "r" },
      { type: "thinking", text: "two", conv_id: "c", run_id: "r" },
      { type: "tool", text: "read", conv_id: "c", run_id: "r" },
      { type: "text_delta", text: "answer ", conv_id: "c", run_id: "r" },
      { type: "text_delta", text: "text", conv_id: "c", run_id: "r" },
    ];

    expect(coalesceAgentEvents(events)).toEqual([
      { type: "thinking", text: "one two", conv_id: "c", run_id: "r" },
      events[2],
      { type: "text_delta", text: "answer text", conv_id: "c", run_id: "r" },
    ]);
  });

  it("does not merge different runs and keeps only the latest adjacent status", () => {
    const events: AgentEvent[] = [
      { type: "status", text: "starting", conv_id: "c", run_id: "r" },
      { type: "status", text: "working", conv_id: "c", run_id: "r" },
      { type: "thinking", text: "first", conv_id: "c", run_id: "r" },
      { type: "thinking", text: "second", conv_id: "c", run_id: "r2" },
    ];

    expect(coalesceAgentEvents(events)).toEqual([events[1], events[2], events[3]]);
  });
});

describe("replayedCount", () => {
  it("marks the backlog that existed when the page loaded as history", () => {
    // Loaded at server event 700: the first page (201..700) is all history.
    expect(replayedCount(700, 500, 700)).toBe(500);
    // The next page straddles the mark: 701.. are live.
    expect(replayedCount(705, 5, 700)).toBe(0);
    expect(replayedCount(702, 4, 700)).toBe(2);
    // A page loaded on an empty backlog replays nothing.
    expect(replayedCount(3, 3, 0)).toBe(0);
  });
});

describe("subscribeAgentEventsImmediate", () => {
  it("hears each event as it arrives, with no frame (a minimized window paints none)", () => {
    const raf = window.requestAnimationFrame;
    window.requestAnimationFrame = () => 0; // frames never come, as in a minimized window
    vi.stubGlobal("fetch", () => new Promise(() => {})); // the bus's event poll never answers here
    try {
      const heard: AgentEvent[] = [];
      const stop = subscribeAgentEventsImmediate((event) => heard.push(event));
      pushLocalAgentEvent({ type: "direct_rtc", session: "s1" } as unknown as AgentEvent);
      pushLocalAgentEvent({ type: "text_delta", text: "a", conv_id: "c", run_id: "r" });
      pushLocalAgentEvent({ type: "text_delta", text: "b", conv_id: "c", run_id: "r" });
      expect(heard.map((e) => e.type)).toEqual(["direct_rtc", "text_delta", "text_delta"]);
      stop();
      pushLocalAgentEvent({ type: "text_delta", text: "c", conv_id: "c", run_id: "r" });
      expect(heard).toHaveLength(3);
    } finally {
      window.requestAnimationFrame = raf;
      vi.unstubAllGlobals();
    }
  });
});
