/**
 * Speech failures the user can fix in one click. Every listen engine reports
 * through SpeechError so the composer toast and the live panel show the same
 * plain message + the same fix button.
 */

import { getApi } from "../hooks/usePanelApi";
import { openLlmsProviderSettings, requestOpenSettings } from "../navigation/openSettingsTab";

export type SpeechErrorAction =
  /** Windows Settings → Privacy → Speech → Online speech recognition. */
  | "speech_privacy"
  /** Windows Settings → Privacy → Microphone. */
  | "mic_privacy"
  /** Windows Settings → Sound (pick / plug in a mic). */
  | "sound_input"
  /** Settings → LLMs → OpenAI key. */
  | "openai_key"
  /** Settings → Audio (Ducky's own mic permission). */
  | "app_mic";

export class SpeechError extends Error {
  readonly action?: SpeechErrorAction;
  readonly code?: string;

  constructor(message: string, action?: SpeechErrorAction, code?: string) {
    super(message);
    this.name = "SpeechError";
    this.action = action;
    this.code = code;
  }
}

/** Windows speech helper codes → fix button. */
export function actionForCode(code: string | undefined): SpeechErrorAction | undefined {
  if (code === "speech_privacy") return "speech_privacy";
  if (code === "mic_privacy") return "mic_privacy";
  if (code === "no_mic") return "sound_input";
  return undefined;
}

/** Classify any thrown value (old string errors included) into a SpeechError. */
export function toSpeechError(err: unknown): SpeechError {
  if (err instanceof SpeechError) return err;
  const message = err instanceof Error ? err.message : String(err || "Speech failed");
  if (/OpenAI key|OpenAI gateway/i.test(message)) return new SpeechError(message, "openai_key");
  if (/Settings → Audio|Microphone blocked/i.test(message)) return new SpeechError(message, "app_mic");
  if (/mic privacy|Windows mic|denied by the system/i.test(message)) return new SpeechError(message, "mic_privacy");
  return new SpeechError(message);
}

export function speechErrorActionLabel(action: SpeechErrorAction): string {
  switch (action) {
    case "speech_privacy":
      return "Turn on Windows speech";
    case "mic_privacy":
      return "Open mic privacy";
    case "sound_input":
      return "Sound settings";
    case "openai_key":
      return "Add OpenAI key";
    case "app_mic":
      return "Audio settings";
  }
}

export function runSpeechErrorAction(action: SpeechErrorAction): void {
  const api = getApi();
  switch (action) {
    case "speech_privacy":
    case "mic_privacy":
    case "sound_input":
      void api?.voice_open_windows_settings?.(action);
      return;
    case "openai_key":
      openLlmsProviderSettings("openai");
      return;
    case "app_mic":
      requestOpenSettings("Audio");
      return;
  }
}
