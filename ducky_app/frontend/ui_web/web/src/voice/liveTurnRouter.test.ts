import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => null }));

import { _resetLiveLatency, getLiveLatencySamples, markLiveFirstAudio, markLiveTurnEnd } from "./liveLatency";
import { isStopCommand, routeLiveTurn, type LaneReply, type LiveTurnDeps } from "./liveTurnRouter";

/** A chat agent mid-run: sends while running wait in a queue and go out when the step ends. */
class FakeAgent {
  running = true;
  queue: string[] = [];
  received: string[] = [];
  cancelled = false;
  send(text: string) {
    if (this.running) this.queue.push(text);
    else this.received.push(text);
  }
  finishStep() {
    this.running = false;
    const next = this.queue.shift();
    if (next !== undefined) {
      this.received.push(next);
      this.running = true;
    }
  }
  cancel() {
    this.cancelled = true;
    this.running = false;
  }
}

function deps(agent: FakeAgent, reply: LaneReply | null, spoken: string[]): LiveTurnDeps {
  return {
    askLane: vi.fn(async () => reply),
    deliver: (t) => agent.send(t),
    cancel: () => agent.cancel(),
    speak: (t) => spoken.push(t),
  };
}

beforeEach(() => _resetLiveLatency());

describe("stop words", () => {
  it("matches stop / cancel phrasing only", () => {
    for (const s of ["stop", "Stop.", "cancel", "cancel that", "okay stop it", "please stop now!"]) {
      expect(isStopCommand(s)).toBe(true);
    }
    for (const s of ["stop the music in the level", "don't stop", "can you cancel the timer device"]) {
      expect(isStopCommand(s)).toBe(false);
    }
  });
});

describe("routeLiveTurn", () => {
  it("answer only: speaks the voice model's reply and starts no agent turn", async () => {
    const agent = new FakeAgent();
    agent.running = false;
    const spoken: string[] = [];
    const d = deps(agent, { ok: true, action: "answer", text: "Compiling, 2 errors left." }, spoken);
    const out = await routeLiveTurn("what are you doing?", { agentRunning: false }, d);
    expect(out).toBe("answered");
    expect(spoken).toEqual(["Compiling, 2 errors left."]);
    expect(agent.received).toEqual([]);
    expect(agent.queue).toEqual([]);
  });

  it("hand to agent: says one line and sends the words to the chat", async () => {
    const agent = new FakeAgent();
    agent.running = false;
    const spoken: string[] = [];
    const d = deps(agent, { ok: true, action: "agent", text: "On it, making it blue." }, spoken);
    expect(await routeLiveTurn("make the button blue", { agentRunning: false }, d)).toBe("agent");
    expect(spoken).toEqual(["On it, making it blue."]);
    expect(agent.received).toEqual(["make the button blue"]);
  });

  it("no voice model: the turn still reaches the agent", async () => {
    const agent = new FakeAgent();
    agent.running = false;
    const spoken: string[] = [];
    expect(await routeLiveTurn("hello", { agentRunning: false }, deps(agent, null, spoken))).toBe("agent");
    expect(spoken).toEqual([]);
    expect(agent.received).toEqual(["hello"]);
  });
});

describe("spoken instructions during a run", () => {
  it("a follow-up is queued and delivered after the current step", async () => {
    const agent = new FakeAgent();
    const spoken: string[] = [];
    const d = deps(agent, { ok: true, action: "agent", text: "Sure, after this step." }, spoken);
    await routeLiveTurn("also make it blue", { agentRunning: true }, d);
    expect(agent.cancelled).toBe(false);
    expect(agent.received).toEqual([]);
    expect(agent.queue).toEqual(["also make it blue"]);
    agent.finishStep();
    expect(agent.received).toEqual(["also make it blue"]);
  });

  it("a question while it runs is answered without touching the run", async () => {
    const agent = new FakeAgent();
    const d = deps(agent, { ok: true, action: "answer", text: "Fixing the second error." }, []);
    await routeLiveTurn("how is it going?", { agentRunning: true }, d);
    expect(agent.queue).toEqual([]);
    expect(agent.running).toBe(true);
  });

  it("'stop' cancels the run without asking the voice model", async () => {
    const agent = new FakeAgent();
    const spoken: string[] = [];
    const d = deps(agent, { ok: true, action: "answer", text: "x" }, spoken);
    expect(await routeLiveTurn("stop", { agentRunning: true }, d)).toBe("stopped");
    expect(agent.cancelled).toBe(true);
    expect(d.askLane).not.toHaveBeenCalled();
    expect(spoken).toEqual(["Stopped."]);
    expect(agent.queue).toEqual([]);
  });
});

describe("speech-end to first-audio latency", () => {
  it("starts at turn end, stops at first audio and records the lane", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    markLiveTurnEnd("chat-a", "agent", 1000);
    const agent = new FakeAgent();
    agent.running = false;
    await routeLiveTurn("what are you doing?", { agentRunning: false }, deps(agent, { ok: true, action: "answer", text: "Compiling." }, []));
    const sample = markLiveFirstAudio(2100);
    expect(sample).toEqual({ chatId: "chat-a", lane: "voice lane", ms: 1100, label: "live turn 1.1 s (voice lane)" });
    expect(markLiveFirstAudio(3000)).toBeNull();
    expect(getLiveLatencySamples().map((s) => s.label)).toEqual(["live turn 1.1 s (voice lane)"]);
    expect(info).toHaveBeenCalledWith("[live-voice] live turn 1.1 s (voice lane)");
    info.mockRestore();
  });
});
