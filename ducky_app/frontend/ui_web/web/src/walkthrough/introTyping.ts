/**
 * The welcome ducky's first message types itself out once, right after the setup. Its text
 * is written ahead of time, so nothing calls a model and no tokens are spent. While armed,
 * the bubble that offers walkthroughs types; everything else renders as usual.
 */
import { useEffect, useLayoutEffect, useState } from "react";

export const INTRO_WORD_MS = 55;

let state: "off" | "armed" | "typing" = "off";
const waiters = new Set<() => void>();

/** The next welcome message types itself out. */
export function armIntro(): void {
  state = "armed";
}

/** Nothing to type after all (no welcome ducky was made). */
export function disarmIntro(): void {
  if (state === "armed") state = "off";
}

function finishIntro(): void {
  state = "off";
  for (const done of [...waiters]) done();
  waiters.clear();
}

/** Resolves once the intro is typed out, or after `timeoutMs` when no bubble showed it. */
export function whenIntroDone(timeoutMs = 12_000): Promise<void> {
  if (state === "off") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      globalThis.clearTimeout(timer);
      resolve();
    };
    const timer = globalThis.setTimeout(() => {
      waiters.delete(done);
      state = "off";
      resolve();
    }, timeoutMs);
    waiters.add(done);
  });
}

/** How much of `text` shows after the next word, given `shown` characters so far. */
export function nextIntroLength(text: string, shown: number): number {
  const word = /\s*\S+/y;
  word.lastIndex = shown;
  return word.exec(text) ? word.lastIndex : text.length;
}

/** The part of `text` on screen while the intro types, or null when it shows in full. */
export function useIntroTyping(text: string, offersTours: boolean): string | null {
  const [shown, setShown] = useState<string | null>(null);
  // Layout effect: the full text must not flash before typing starts.
  useLayoutEffect(() => {
    if (!offersTours || state === "off") return;
    state = "typing";
    setShown("");
  }, [offersTours]);
  useEffect(() => {
    if (shown === null) return;
    if (shown.length >= text.length) {
      setShown(null);
      finishIntro();
      return;
    }
    const timer = globalThis.setTimeout(() => setShown(text.slice(0, nextIntroLength(text, shown.length))), INTRO_WORD_MS);
    return () => globalThis.clearTimeout(timer);
  }, [shown, text]);
  return shown;
}

/** Test helper. */
export function _resetIntroForTests(): void {
  state = "off";
  waiters.clear();
}
