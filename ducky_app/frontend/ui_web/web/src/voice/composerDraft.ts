/**
 * Live dictation into the chat box: the text you had, plus confirmed words,
 * plus the phrase still being recognized. Typing mid-dictation is kept — your
 * edit becomes the new starting text and recognition continues after it.
 */

export type DictationDraft = {
  /** Box text when dictation began (or after the user's latest edit). */
  prefix: string;
  /** Confirmed words since then. */
  spoken: string;
  /** The phrase still being recognized. */
  interim: string;
  /** Exactly what we last put in the box. */
  written: string;
  /** The interim part of `written` (stripped if the user edits around it). */
  shownInterim: string;
};

/** Join two runs of words with one space unless a break is already there. */
export function joinWords(a: string, b: string): string {
  if (!b) return a;
  if (!a) return b;
  return /\s$/.test(a) || /^\s/.test(b) ? a + b : `${a} ${b}`;
}

export function beginDraft(current: string): DictationDraft {
  return { prefix: current, spoken: "", interim: "", written: current, shownInterim: "" };
}

/** Next box text for `draft`, given what the box holds now. Updates `draft`. */
export function renderDraft(draft: DictationDraft, current: string): string {
  if (current !== draft.written) {
    let base = current;
    if (draft.shownInterim && base.endsWith(draft.shownInterim)) {
      base = base.slice(0, base.length - draft.shownInterim.length).trimEnd();
    }
    draft.prefix = base;
    draft.spoken = "";
  }
  const next = joinWords(draft.prefix, joinWords(draft.spoken, draft.interim));
  draft.written = next;
  draft.shownInterim = draft.interim;
  return next;
}
