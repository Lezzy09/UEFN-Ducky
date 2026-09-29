/** Composer @ / / tokens and the markdown links they insert. */

export type ChatRefTrigger = "@" | "/" | "~";

/** ``pipeline`` is how chats before Workflows linked a workflow; it still opens one. */
export type ChatRefKind = "ducky" | "profile" | "skill" | "subskill" | "mcp" | "plugin" | "file" | "workflow" | "pipeline";

export interface ChatRef {
  trigger: ChatRefTrigger;
  id: string;
  label: string;
  group: string;
  description?: string;
  href: string;
  /** Bundled or custom ducky portrait, for chats and library agents. */
  duckyStyle?: string;
  /** Plugin image, or a short emoji when the plugin has no image. */
  iconUrl?: string;
}

const HREF_RE = /^(ducky|profile|skill|subskill|mcp|plugin|file|workflow|pipeline):([A-Za-z0-9_./:-]+)$/;

export function parseChatRefHref(href: string): { kind: ChatRefKind; id: string } | null {
  const match = HREF_RE.exec((href || "").trim());
  if (!match) return null;
  return { kind: match[1] as ChatRefKind, id: match[2] };
}

export function chatRefMarkdown(label: string, href: string): string {
  const kind = parseChatRefHref(href)?.kind;
  const sigil: ChatRefTrigger = kind === "ducky" || kind === "profile" ? "@" : "/";
  const safe = label.replace(/[\[\]]/g, "").trim() || "reference";
  return `[${sigil}${safe}](${href})`;
}

export interface CaretToken {
  trigger: ChatRefTrigger;
  query: string;
  start: number;
  end: number;
}

/** The @ or / word touching the caret, or a ~ search that may contain spaces. */
export function readCaretToken(text: string, caret: number): CaretToken | null {
  const end = Math.max(0, Math.min(caret, text.length));
  let start = end;
  while (start > 0 && !/\s/.test(text[start - 1])) start -= 1;
  const token = text.slice(start, end);
  const match = /^([@/])(.*)$/.exec(token);
  if (match) return { trigger: match[1] as ChatRefTrigger, query: match[2], start, end };
  const lineStart = text.lastIndexOf("\n", Math.max(0, end - 1)) + 1;
  const line = text.slice(lineStart, end);
  let tilde = -1;
  for (let i = 0; i < line.length; i += 1) {
    if (line[i] === "~" && (i === 0 || /\s/.test(line[i - 1]))) tilde = i;
  }
  if (tilde < 0) return null;
  return { trigger: "~", query: line.slice(tilde + 1), start: lineStart + tilde, end };
}

/** Snippet when every word of the query appears in the text. Null when it does not. */
export function innerTextHit(text: string, query: string): string | null {
  const toks = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!toks.length || toks.join("").length < 2) return null;
  const hay = text.toLowerCase();
  if (!toks.every((tok) => hay.includes(tok))) return null;
  const at = hay.indexOf(toks[0]);
  const from = Math.max(0, at - 28);
  const to = Math.min(text.length, at + toks[0].length + 48);
  let snip = text.slice(from, to).replace(/\s+/g, " ").trim();
  if (from > 0) snip = `…${snip}`;
  if (to < text.length) snip = `${snip}…`;
  return snip;
}

export function insertChatRef(
  text: string,
  token: CaretToken,
  label: string,
  href: string,
): { text: string; caret: number } {
  const md = `${chatRefMarkdown(label, href)} `;
  const next = text.slice(0, token.start) + md + text.slice(token.end);
  return { text: next, caret: token.start + md.length };
}

export function filterChatRefs(refs: ChatRef[], query: string): ChatRef[] {
  const q = query.trim().toLowerCase();
  if (!q) return refs;
  return refs.filter((ref) => {
    const label = ref.label.toLowerCase();
    const id = ref.id.toLowerCase();
    const desc = (ref.description || "").toLowerCase();
    return label.includes(q) || id.includes(q) || desc.includes(q);
  });
}

/** First row wins when trigger+id collide. */
export function dedupeChatRefs(refs: ChatRef[]): ChatRef[] {
  const seen = new Set<string>();
  const out: ChatRef[] = [];
  for (const ref of refs) {
    const key = `${ref.trigger}\0${ref.id}`;
    if (seen.has(key)) continue;
    if (!parseChatRefHref(ref.href)) continue;
    seen.add(key);
    out.push(ref);
  }
  return out;
}

const TOKEN_RE =
  /\[(@|\/)([^\]]+)\]\((ducky|profile|skill|subskill|mcp|plugin|file|workflow|pipeline):([A-Za-z0-9_./:-]+)\)/g;

export interface ChatRefToken {
  label: string;
  href: string;
  start: number;
  end: number;
}

/** Name shown on the chip. The stored markdown still carries the @ or /. */
/** This project, Global (no island), or the other island's name. */
export function chatMentionGroup(slug: string, openSlug: string, projectName: string): string {
  const s = slug.trim();
  if (!s || s === "_no_project") return "Global";
  if (openSlug.trim() && s === openSlug.trim()) return "This project";
  return projectName.trim() || s;
}

/** Other islands first so a long This project list does not hide them. */
export function orderChatMentions(rows: ChatRef[]): ChatRef[] {
  const buckets = new Map<string, ChatRef[]>();
  for (const row of rows) {
    const list = buckets.get(row.group) ?? [];
    list.push(row);
    buckets.set(row.group, list);
  }
  const others = [...buckets.keys()]
    .filter((name) => name !== "This project" && name !== "Global")
    .sort((a, b) => a.localeCompare(b));
  const order = [
    ...others,
    ...(buckets.has("This project") ? ["This project"] : []),
    ...(buckets.has("Global") ? ["Global"] : []),
  ];
  return order.flatMap((name) => buckets.get(name) ?? []);
}

/** ~ opens immediately from the @ and / catalog. Body search fills in later. */
export function instantInnerRefs(
  query: string,
  mentions: ChatRef[],
  slashRefs: ChatRef[],
  files: ChatRef[],
): ChatRef[] {
  const asSearch = (rows: ChatRef[]) => rows.map((row) => ({ ...row, trigger: "~" as const }));
  const q = query.trim();
  if (!q) return asSearch([...mentions, ...slashRefs]).slice(0, 40);
  return asSearch(filterChatRefs([...mentions, ...slashRefs, ...files], q)).slice(0, 24);
}

/** Keep catalog order. A later body hit only replaces the snippet. */
export function mergeInnerRefs(instant: ChatRef[], body: ChatRef[]): ChatRef[] {
  const snippet = new Map(body.map((row) => [row.href, row]));
  const seen = new Set<string>();
  const out: ChatRef[] = [];
  for (const row of instant) {
    seen.add(row.href);
    const extra = snippet.get(row.href);
    out.push(extra ? { ...row, description: extra.description || row.description } : row);
  }
  for (const row of body) {
    if (seen.has(row.href)) continue;
    seen.add(row.href);
    out.push(row);
  }
  return out;
}

export function chatRefDisplayName(label: string): string {
  return label.replace(/^[@/]/, "").trim() || label;
}

/** Grow a delete range so a chip is removed whole, never left as broken markdown. */
export function expandRangeToChips(text: string, start: number, end: number): { start: number; end: number } {
  let a = start;
  let b = end;
  for (const token of findChatRefTokens(text)) {
    if (token.end <= a || token.start >= b) continue;
    if (a > token.start) a = token.start;
    if (b < token.end) b = token.end;
  }
  return { start: a, end: b };
}

/** The chip sitting against the caret, so Backspace and Delete remove it like a word. */
export function chipTouchingCaret(text: string, caret: number, edge: "before" | "after"): ChatRefToken | null {
  for (const token of findChatRefTokens(text)) {
    if (edge === "before" && token.end === caret) return token;
    if (edge === "after" && token.start === caret) return token;
  }
  return null;
}

export function findChatRefTokens(text: string): ChatRefToken[] {
  const out: ChatRefToken[] = [];
  for (const match of text.matchAll(TOKEN_RE)) {
    const start = match.index ?? 0;
    out.push({
      label: `${match[1]}${match[2]}`,
      href: `${match[3]}:${match[4]}`,
      start,
      end: start + match[0].length,
    });
  }
  return out;
}
