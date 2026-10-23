import { useEffect, useState } from "react";

import "../theme/styles/live-voice.css";
import { Icons } from "../icons/Icons";
import { getLiveVoiceState, subscribeLiveVoiceChats, type LiveVoiceState } from "./liveChats";
import { LiveVoicePickers } from "./LiveVoicePickers";
import { runSpeechErrorAction, speechErrorActionLabel } from "./speechErrors";
import { ttsEngine, type TtsProgress } from "./ttsEngine";
import { VoiceOrb, type VoiceOrbStatus } from "./VoiceOrb";

export type LiveVoiceViewProps = {
  chatId: string;
  /** End live voice. */
  onEnd: () => void;
  /** Hide this view and bring back the normal transcript. */
  onShowChat: () => void;
  muted: boolean;
  setMuted: (value: boolean) => void;
  onRetry?: () => void;
  /** One-line work status from the agent (tool step), when the voice lane exports it. */
  workStatus?: string;
  /** Mic stream for the orb's level meter, when one is reachable. */
  micStream?: MediaStream | null;
  /** Force the phone layout on or off; default follows the viewport. */
  narrow?: boolean;
  voiceId?: string;
  speed?: number;
  setVoiceId?: (value: string) => void;
  setSpeed?: (value: number) => void;
  processTalk?: number;
  setProcessTalk?: (value: number) => void;
  chatModel?: string;
  setChatModel?: (value: string) => void;
  codingAgent?: string;
  setCodingAgent?: (value: string) => void;
  showChatModel?: boolean;
};

const NARROW_QUERY = "(max-width: 600px), (orientation: portrait) and (max-width: 900px)";

function readNarrow(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(NARROW_QUERY).matches;
}

/** Phone / portrait layout: orb centered, big controls along the bottom. */
export function useNarrowVoiceLayout(): boolean {
  const [narrow, setNarrow] = useState(readNarrow);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(NARROW_QUERY);
    const onChange = () => setNarrow(mq.matches);
    onChange();
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return narrow;
}

/** Orb + chip status from the live state and TTS progress. */
export function liveViewStatus(state: LiveVoiceState, tts: Pick<TtsProgress, "loading">, muted: boolean): VoiceOrbStatus {
  if (state.status === "error") return "error";
  if (state.status === "speaking") return "speaking";
  if (state.status === "thinking" || state.status === "connecting" || tts.loading) return "thinking";
  if (muted || state.muted || state.status === "muted") return "muted";
  return "listening";
}

const CHIP_LABEL: Record<VoiceOrbStatus, string> = {
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  muted: "Mic muted",
  error: "Mic problem",
};

/** Last sentence of a spoken reply, so the caption stays one line. */
export function lastLine(text: string): string {
  const clean = (text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  const parts = clean.split(/(?<=[.!?])\s+/).filter(Boolean);
  return parts[parts.length - 1] || clean;
}

/** One line under the orb: the user's interim words while they talk, else Ducky's last spoken line. */
export function liveCaption(state: LiveVoiceState, status: VoiceOrbStatus): string {
  if (status === "error") return state.error || "";
  const heard = state.userInterim.trim();
  if (heard && status !== "speaking") return heard;
  return lastLine(state.spokenText) || lastLine(state.lastUserText);
}

/**
 * Full-screen minimal live voice view: orb, a one-line caption, a status chip and
 * mute / end / show chat / settings. Sits over the chat while live voice is on.
 */
export function LiveVoiceView({
  chatId,
  onEnd,
  onShowChat,
  muted,
  setMuted,
  onRetry,
  workStatus = "",
  micStream,
  narrow,
  voiceId = "",
  speed = 1,
  setVoiceId,
  setSpeed,
  processTalk,
  setProcessTalk,
  chatModel,
  setChatModel,
  codingAgent,
  setCodingAgent,
  showChatModel = false,
}: LiveVoiceViewProps) {
  const [state, setState] = useState<LiveVoiceState>(() => getLiveVoiceState(chatId));
  const [tts, setTts] = useState<TtsProgress>(() => ttsEngine.getProgress());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const autoNarrow = useNarrowVoiceLayout();
  const isNarrow = narrow ?? autoNarrow;

  useEffect(() => {
    setState(getLiveVoiceState(chatId));
    return subscribeLiveVoiceChats(() => setState(getLiveVoiceState(chatId)));
  }, [chatId]);

  useEffect(() => ttsEngine.onProgress(setTts), []);

  const status = liveViewStatus(state, tts, muted);
  const caption = liveCaption(state, status);
  const work = workStatus.trim();
  const pickers = Boolean(setVoiceId && setSpeed);
  const micMuted = muted || state.muted;

  return (
    <div
      className={`live-voice-view live-voice-view--${status}${isNarrow ? " live-voice-view--narrow" : ""}`}
      role="dialog"
      aria-label="Live voice"
      data-status={status}
    >
      <div className="live-voice-top">
        <span className={`live-voice-chip live-voice-chip--${status}`} role="status" aria-live="polite">
          <span className="live-voice-chip-dot" aria-hidden />
          {CHIP_LABEL[status]}
          {work ? <span className="live-voice-chip-work"> · {work}</span> : null}
        </span>
      </div>

      <div className="live-voice-stage">
        <VoiceOrb status={status} stream={micStream} />
        <p className="live-voice-caption" title={caption || undefined}>
          {caption || " "}
        </p>
        {state.speakerName ? <p className="live-voice-speaker">{state.speakerName}</p> : null}
        {status === "error" && (state.errorAction || onRetry) ? (
          <div className="live-voice-error-actions">
            {state.errorAction ? (
              <button type="button" className="live-voice-pill" onClick={() => runSpeechErrorAction(state.errorAction!)}>
                {speechErrorActionLabel(state.errorAction)}
              </button>
            ) : null}
            {onRetry ? (
              <button type="button" className="live-voice-pill" onClick={onRetry}>
                Try again
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="live-voice-controls">
        <button
          type="button"
          className="live-voice-btn"
          aria-label="Show chat"
          title="Show chat"
          onClick={onShowChat}
        >
          <Icons.Chat />
        </button>
        <button
          type="button"
          className={`live-voice-btn${micMuted ? " is-on" : ""}`}
          aria-label={micMuted ? "Unmute microphone" : "Mute microphone"}
          aria-pressed={micMuted}
          title={micMuted ? "Unmute mic" : "Mute mic — keep hearing replies"}
          onClick={() => setMuted(!micMuted)}
        >
          {micMuted ? <Icons.MicOff /> : <Icons.Mic />}
        </button>
        <button
          type="button"
          className="live-voice-btn live-voice-btn--end"
          aria-label="End live voice"
          title="End live voice"
          onClick={onEnd}
        >
          <Icons.Close />
        </button>
        {pickers ? (
          <button
            type="button"
            className={`live-voice-btn${settingsOpen ? " is-on" : ""}`}
            aria-label="Voice settings"
            aria-expanded={settingsOpen}
            title="Voice settings"
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <Icons.Settings />
          </button>
        ) : null}
      </div>

      {pickers && settingsOpen && setVoiceId && setSpeed ? (
        <div className="live-voice-sheet" role="dialog" aria-label="Voice settings">
          <div className="live-voice-sheet-head">
            <span>Voice settings</span>
            <button
              type="button"
              className="live-voice-sheet-close"
              aria-label="Close voice settings"
              onClick={() => setSettingsOpen(false)}
            >
              <Icons.Close />
            </button>
          </div>
          <LiveVoicePickers
            voiceId={voiceId}
            speed={speed}
            setVoiceId={setVoiceId}
            setSpeed={setSpeed}
            processTalk={processTalk}
            setProcessTalk={setProcessTalk}
            chatModel={chatModel}
            setChatModel={setChatModel}
            codingAgent={codingAgent}
            setCodingAgent={setCodingAgent}
            showChatModel={showChatModel}
          />
        </div>
      ) : null}
    </div>
  );
}
