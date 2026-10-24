/**
 * Map a TTS chunk onto the assistant bubble. Live voice speaks one sentence
 * at a time, so sourceText is rarely the full message.
 */
export function mapReadAlong(
  messageText: string,
  spokenText: string,
  sourceText: string,
  charIndex: number,
): { spokenText: string; charIndex: number } | null {
  const message = messageText || "";
  if (!message.trim()) return null;
  const raw = [spokenText, sourceText].map((s) => (s || "").trim()).filter(Boolean);
  const chunks = raw.concat(raw.map((s) => s.replace(/^[^\n:]{1,40}:\s+/, "")).filter(Boolean));
  for (const chunk of chunks) {
    if (chunk === message || sourceText === message) {
      return { spokenText: spokenText || message, charIndex };
    }
    const at = message.indexOf(chunk);
    if (at < 0) continue;
    let idx = charIndex;
    if (spokenText && !spokenText.startsWith(chunk)) {
      const prefix = spokenText.indexOf(chunk);
      if (prefix >= 0) idx = Math.max(0, charIndex - prefix);
    }
    return { spokenText: message, charIndex: at + idx };
  }
  return null;
}

/** A word as compared between the spoken text and the formatted reply: markdown
 *  marks (`**`, `##`, backticks) and punctuation dropped, any case. */
function plainWord(word: string): string {
  return word.toLowerCase().replace(/[^\p{L}\p{N}']+/gu, "");
}

/** The word being spoken and how many times it came before it (to find the same one on screen). */
export function spokenWordAt(text: string, charIndex: number): { word: string; occurrence: number } | null {
  const spoken = text || "";
  let start = Math.max(0, Math.min(spoken.length, charIndex));
  while (start > 0 && !/\s/.test(spoken[start - 1]!)) start -= 1;
  let end = start;
  while (end < spoken.length && !/\s/.test(spoken[end]!)) end += 1;
  const word = plainWord(spoken.slice(start, end));
  if (!word) return null;
  let occurrence = 0;
  for (const w of spoken.slice(0, start).split(/\s+/)) if (plainWord(w) === word) occurrence += 1;
  return { word, occurrence };
}

/** The range of that word in the rendered reply (its `occurrence`-th appearance), or null. */
export function findWordRange(root: Node, word: string, occurrence: number): Range | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let seen = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = node.nodeValue || "";
    for (const m of value.matchAll(/[\p{L}\p{N}']+/gu)) {
      if (plainWord(m[0]) !== word) continue;
      if (seen === occurrence) {
        const range = document.createRange();
        range.setStart(node, m.index ?? 0);
        range.setEnd(node, (m.index ?? 0) + m[0].length);
        return range;
      }
      seen += 1;
    }
  }
  return null;
}

const HIGHLIGHT_NAME = "ducky-tts-word";

type HighlightRegistry = { set: (name: string, value: unknown) => void; delete: (name: string) => void };

/** Mark the spoken word inside the formatted reply (CSS Custom Highlight API: nothing in the
 *  page changes). Returns false where the API is missing; the reply still reads normally. */
export function markSpokenWord(root: Node | null, spokenText: string, charIndex: number): boolean {
  const registry = (globalThis.CSS as unknown as { highlights?: HighlightRegistry } | undefined)?.highlights;
  const HighlightCtor = (globalThis as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  if (!registry || !HighlightCtor || !root) return false;
  const at = spokenWordAt(spokenText, charIndex);
  const range = at ? findWordRange(root, at.word, at.occurrence) : null;
  if (range) registry.set(HIGHLIGHT_NAME, new HighlightCtor(range));
  return true;
}

export function clearSpokenWord(): void {
  (globalThis.CSS as unknown as { highlights?: HighlightRegistry } | undefined)?.highlights?.delete(HIGHLIGHT_NAME);
}

/**
 * Plain-text karaoke highlight while a message is being spoken.
 */

export function TtsReadAlong({ spokenText, charIndex }: { spokenText: string; charIndex: number }) {
  const spoken = (spokenText || "").trim();
  if (!spoken) return null;
  const i = Math.max(0, Math.min(spoken.length, charIndex));
  let wordEnd = i;
  while (wordEnd < spoken.length && !/\s/.test(spoken[wordEnd]!)) wordEnd += 1;
  return (
    <p className="tts-readalong selectable-text">
      <span className="tts-readalong-spoken">{spoken.slice(0, i)}</span>
      <span className="tts-readalong-current">{spoken.slice(i, wordEnd) || " "}</span>
      <span className="tts-readalong-rest">{spoken.slice(wordEnd)}</span>
    </p>
  );
}
