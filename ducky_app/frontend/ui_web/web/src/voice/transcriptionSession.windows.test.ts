import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WinSttEvent } from "../types/panel";

type Poll = { ok: boolean; events: WinSttEvent[]; cursor: number; active: boolean };

const queue: Poll[] = [];
const calls: string[] = [];
let startResult: Record<string, unknown> = { ok: true, session: "s1", cursor: 0 };

const api = {
  get_key_status: vi.fn(async () => ({ openai: false })),
  voice_win_stt_start: vi.fn(async () => {
    calls.push("start");
    return startResult;
  }),
  voice_win_stt_poll: vi.fn(async (): Promise<Poll> => {
    const next = queue.shift();
    if (next) return next;
    await new Promise((r) => setTimeout(r, 5));
    return { ok: true, events: [], cursor: 0, active: true };
  }),
  voice_win_stt_stop: vi.fn(async () => {
    calls.push("stop");
    queue.push({
      ok: true,
      events: [
        { t: "final", sid: "s1", text: "and the last words" },
        { t: "ended", sid: "s1", status: "Success" },
      ],
      cursor: 9,
      active: false,
    });
    return { ok: true };
  }),
  voice_win_stt_cancel: vi.fn(async () => {
    calls.push("cancel");
    return { ok: true };
  }),
};

vi.mock("../hooks/usePanelApi", () => ({
  getApi: () => api,
  isRemote: () => false,
}));

vi.mock("./micPermission", () => ({
  requestMicAccess: vi.fn(),
}));

const { createBatchTranscriptionSession } = await import("./transcriptionSession");

const flush = () => new Promise((r) => setTimeout(r, 30));

describe("Windows dictation session", () => {
  beforeEach(() => {
    queue.length = 0;
    calls.length = 0;
    startResult = { ok: true, session: "s1", cursor: 0 };
  });

  it("streams interim words, delivers finals, and keeps the last phrase on stop", async () => {
    const interims: string[] = [];
    const finals: string[] = [];
    const states: string[] = [];
    const session = createBatchTranscriptionSession();
    queue.push({
      ok: true,
      events: [
        { t: "interim", sid: "s1", text: "make a" },
        { t: "interim", sid: "s1", text: "make a door" },
        { t: "final", sid: "s1", text: "Make a door." },
      ],
      cursor: 3,
      active: true,
    });
    await session.start({
      onInterim: (t) => interims.push(t),
      onFinal: (t) => finals.push(t),
      onStateChange: (s) => states.push(s),
    });
    await flush();
    expect(interims).toContain("make a door");
    expect(finals).toEqual(["Make a door."]);

    await session.stop();
    expect(calls).toEqual(["start", "stop"]);
    expect(finals).toEqual(["Make a door.", "and the last words"]);
    expect(states[0]).toBe("connecting");
    expect(states).toContain("listening");
    expect(states[states.length - 1]).toBe("idle");
  });

  it("turns the Windows privacy block into a fixable error", async () => {
    startResult = { ok: false, code: "speech_privacy", error: "Windows speech is off." };
    const session = createBatchTranscriptionSession();
    await expect(session.start({})).rejects.toMatchObject({
      message: "Windows speech is off.",
      action: "speech_privacy",
    });
  });
});
