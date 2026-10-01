import { describe, expect, it } from "vitest";

import {
  isLikelyEcho,
  liveTtsBusy,
  shouldAcceptLiveFinal,
  shouldReturnToListeningAfterAnswer,
} from "./liveTurnGates";

describe("liveTurnGates", () => {
  it("rejects finals while TTS is busy (speaker echo)", () => {
    expect(shouldAcceptLiveFinal({ isSpeaking: true, queueLength: 0 })).toBe(false);
    expect(shouldAcceptLiveFinal({ isSpeaking: false, queueLength: 2 })).toBe(false);
    expect(liveTtsBusy(true, 0)).toBe(true);
  });

  it("accepts finals after barge-in cleared speech", () => {
    expect(shouldAcceptLiveFinal({ isSpeaking: false, queueLength: 0 })).toBe(true);
  });

  it("returns to listening when the answer finished and nothing else is queued", () => {
    expect(
      shouldReturnToListeningAfterAnswer({ speakingAfterAnswer: true, moreUtterancesQueued: false }),
    ).toBe(true);
    expect(
      shouldReturnToListeningAfterAnswer({ speakingAfterAnswer: true, moreUtterancesQueued: true }),
    ).toBe(false);
    expect(
      shouldReturnToListeningAfterAnswer({ speakingAfterAnswer: false, moreUtterancesQueued: false }),
    ).toBe(false);
  });
});

describe("isLikelyEcho", () => {
  const spoken = "I placed three spawn pads near the castle gate.";

  it("treats Ducky's own words coming back through the mic as echo", () => {
    expect(isLikelyEcho("spawn pads near the castle", spoken)).toBe(true);
    expect(isLikelyEcho("castle", spoken)).toBe(true);
  });

  it("lets a real interruption through", () => {
    expect(isLikelyEcho("wait stop that's wrong", spoken)).toBe(false);
    expect(isLikelyEcho("no use the north gate instead", spoken)).toBe(false);
  });
});
