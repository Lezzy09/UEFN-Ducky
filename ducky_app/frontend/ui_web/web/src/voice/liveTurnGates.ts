/**
 * Live-mic transcript gates — keep echo from the speakers out of the send loop.
 */

/** True while Ducky audio is still playing or queued (speaker echo risk). */
export function liveTtsBusy(isSpeaking: boolean, queueLength: number): boolean {
  return Boolean(isSpeaking || queueLength > 0);
}

/**
 * Accept a VAD final as a user turn only when TTS is quiet.
 * After barge-in clears speech, isSpeaking/queue are false so the same utterance can send.
 */
export function shouldAcceptLiveFinal(opts: {
  isSpeaking: boolean;
  queueLength: number;
}): boolean {
  return !liveTtsBusy(opts.isSpeaking, opts.queueLength);
}

/** After the answer finishes speaking, always return to listening (don't wait on agentRunning). */
export function shouldReturnToListeningAfterAnswer(opts: {
  speakingAfterAnswer: boolean;
  moreUtterancesQueued: boolean;
}): boolean {
  return opts.speakingAfterAnswer && !opts.moreUtterancesQueued;
}

function words(text: string): string[] {
  return (text || "").toLowerCase().match(/[\p{L}\p{N}']+/gu) || [];
}

/**
 * True when what the mic heard is probably Ducky's own voice from the speakers
 * (or too little to tell). Real interruptions are 2+ words that mostly are not
 * in the line being spoken.
 */
export function isLikelyEcho(heard: string, spoken: string): boolean {
  const heardWords = words(heard);
  if (heardWords.length < 2) return true;
  const spokenWords = new Set(words(spoken));
  if (!spokenWords.size) return false;
  const overlap = heardWords.filter((w) => spokenWords.has(w)).length;
  return overlap / heardWords.length >= 0.6;
}
