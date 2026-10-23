/**
 * Where a finished live turn goes: "stop" / "cancel" stops the run, everything else asks
 * the fast voice model first. It answers on its own, or says one line and hands the turn
 * to the chat's agent (queued as the next message while a run is going).
 */

import { getApi } from "../hooks/usePanelApi";
import { setLiveTurnLane } from "./liveLatency";
import { resolveVoiceModel } from "./voiceSettings";
import { getWorkStatus } from "./workStatus";

export type LaneReply = { ok: boolean; action: "answer" | "agent" | "none"; text: string; error?: string };

export type LiveTurnDeps = {
  /** Ask the voice model about this turn; null when it is unavailable. */
  askLane: (text: string, agentRunning: boolean) => Promise<LaneReply | null>;
  /** Hand the words to the chat's agent (the chat queues them while a run is going). */
  deliver: (text: string) => void;
  /** Stop the running agent. */
  cancel: () => void;
  /** Speak a short line now. */
  speak: (text: string) => void;
};

export type LiveTurnOutcome = "stopped" | "answered" | "agent" | "empty";

const STOP_RE = /^(?:ok(?:ay)?[,\s]+)?(?:please\s+)?(?:stop|cancel|halt|abort)(?:\s+(?:it|that|this|now|please|the run|everything))*[\s.!]*$/i;

export function isStopCommand(text: string): boolean {
  return STOP_RE.test((text || "").trim());
}

export async function routeLiveTurn(
  text: string,
  ctx: { agentRunning: boolean },
  deps: LiveTurnDeps,
): Promise<LiveTurnOutcome> {
  const said = (text || "").trim();
  if (!said) return "empty";
  if (isStopCommand(said)) {
    setLiveTurnLane("stop");
    if (ctx.agentRunning) {
      deps.cancel();
      deps.speak("Stopped.");
    }
    return "stopped";
  }
  let reply: LaneReply | null = null;
  try {
    reply = await deps.askLane(said, ctx.agentRunning);
  } catch {
    reply = null;
  }
  if (reply?.ok && reply.action === "answer" && reply.text.trim()) {
    setLiveTurnLane("voice lane");
    deps.speak(reply.text.trim());
    return "answered";
  }
  if (reply?.ok && reply.action === "agent" && reply.text.trim()) {
    setLiveTurnLane("voice lane");
    deps.speak(reply.text.trim());
  } else {
    setLiveTurnLane("agent");
  }
  deps.deliver(said);
  return "agent";
}

type VoiceLaneTurnApi = {
  voice_lane_turn?: (
    convId: string,
    text: string,
    workStatus: string,
    agentRunning: boolean,
    model: string,
  ) => Promise<LaneReply>;
};

const LANE_TIMEOUT_MS = 8000;

/** The real voice-lane call: compact context from the backend, this chat's voice model. */
export function voiceLaneAsker(chatId: string, timeoutMs = LANE_TIMEOUT_MS) {
  return async (text: string, agentRunning: boolean): Promise<LaneReply | null> => {
    const api = getApi() as unknown as VoiceLaneTurnApi | null;
    if (!api?.voice_lane_turn) return null;
    const call = api.voice_lane_turn(chatId, text, getWorkStatus(chatId), agentRunning, resolveVoiceModel(chatId));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), timeoutMs);
    });
    try {
      return await Promise.race([call, timeout]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  };
}
