import { afterEach, describe, expect, it, vi } from "vitest";

import { _resetSpokenReplyGate, noteUserTurn, userAwaitsReply } from "./spokenReplyGate";

describe("spokenReplyGate", () => {
  afterEach(() => {
    _resetSpokenReplyGate();
    vi.useRealTimers();
  });

  it("stays quiet for chats the user never sent in (background runs)", () => {
    expect(userAwaitsReply("bg-automation")).toBe(false);
  });

  it("speaks replies to a turn the user sent, then expires", () => {
    vi.useFakeTimers();
    noteUserTurn("chat-a");
    expect(userAwaitsReply("chat-a")).toBe(true);
    expect(userAwaitsReply("chat-b")).toBe(false);
    vi.advanceTimersByTime(11 * 60_000);
    expect(userAwaitsReply("chat-a")).toBe(false);
  });
});
