// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

import { MAX_BITRATE, MAX_FPS, START_BITRATE, START_FPS, tuneSender } from "./remoteCapture";

afterEach(() => vi.useRealTimers());

it("starts a stream modest and raises it to full quality once the link has had a moment", async () => {
  // Oct 11 2026: a phone opening the stream lagged, then raced to catch up: the first
  // frames went out at 20 Mbps / 60 fps before the link had measured its bandwidth.
  vi.useFakeTimers();
  const applied: Array<{ bitrate?: number; fps?: number }> = [];
  let params: RTCRtpSendParameters = { encodings: [{}] } as unknown as RTCRtpSendParameters;
  const sender = {
    getParameters: () => params,
    setParameters: async (next: RTCRtpSendParameters) => {
      params = next;
      applied.push({ bitrate: next.encodings[0].maxBitrate, fps: next.encodings[0].maxFramerate });
    },
  } as unknown as RTCRtpSender;
  await tuneSender(sender, 4000);
  expect(applied).toEqual([{ bitrate: START_BITRATE, fps: START_FPS }]);
  await vi.advanceTimersByTimeAsync(4000);
  expect(applied.at(-1)).toEqual({ bitrate: MAX_BITRATE, fps: MAX_FPS });
});
