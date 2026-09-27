import { expect, it } from "vitest";
import {
  chipTouchingCaret,
  chatMentionGroup,
  chatRefDisplayName,
  chatRefMarkdown,
  dedupeChatRefs,
  expandRangeToChips,
  filterChatRefs,
  findChatRefTokens,
  innerTextHit,
  insertChatRef,
  instantInnerRefs,
  mergeInnerRefs,
  orderChatMentions,
  parseChatRefHref,
  readCaretToken,
  type ChatRef,
} from "./chatReferences";

it("reads the token at the caret, including mid-sentence", () => {
  const text = "ask @gen about /verse";
  expect(readCaretToken(text, text.indexOf("@") + 4)).toEqual({
    trigger: "@",
    query: "gen",
    start: text.indexOf("@"),
    end: text.indexOf("@") + 4,
  });
  expect(readCaretToken(text, text.length)?.trigger).toBe("/");
  expect(readCaretToken("fix Content/Verse", 16)).toBeNull();
  expect(readCaretToken("mail foo@bar", 12)).toBeNull();
  expect(readCaretToken("/model", 6)).toMatchObject({ trigger: "/", query: "model" });
  const tilde = "see ~ledger props";
  expect(readCaretToken(tilde, tilde.length)).toMatchObject({ trigger: "~", query: "ledger props" });
  expect(readCaretToken("foo~bar", 7)).toBeNull();
  expect(readCaretToken("~keep @gen", "~keep @gen".length)?.trigger).toBe("@");
});

it("replaces only the active token", () => {
  const text = "ping @gen please";
  const token = readCaretToken(text, text.indexOf("@") + 4)!;
  const next = insertChatRef(text, token, "General Helper", "ducky:abc");
  expect(next.text).toBe("ping [@General Helper](ducky:abc)  please");
  expect(next.text.slice(next.caret - 1, next.caret)).toBe(" ");
});

it("keeps the first row when trigger and id collide", () => {
  const rows: ChatRef[] = [
    { trigger: "/", id: "verse", label: "Verse", group: "Skills", href: "skill:verse" },
    { trigger: "/", id: "verse", label: "Other", group: "Plugins", href: "skill:other" },
    { trigger: "/", id: "bad", label: "Bad", group: "Plugins", href: "javascript:alert(1)" },
  ];
  expect(dedupeChatRefs(rows).map((row) => row.label)).toEqual(["Verse"]);
});

it("filters references and parses the stored link", () => {
  const rows: ChatRef[] = [
    { trigger: "@", id: "a", label: "General Helper", group: "This project", href: "ducky:a" },
    { trigger: "@", id: "b", label: "Verse Coder", group: "Global", href: "profile:verse-coder" },
  ];
  expect(filterChatRefs(rows, "gen").map((row) => row.id)).toEqual(["a"]);
  expect(chatRefMarkdown("Verse Coder", "profile:verse-coder")).toBe("[@Verse Coder](profile:verse-coder)");
  expect(chatRefDisplayName("@Animation Artist")).toBe("Animation Artist");
  expect(chatRefDisplayName("/UEFN Niagara")).toBe("UEFN Niagara");
  expect(parseChatRefHref("skill:verse")).toEqual({ kind: "skill", id: "verse" });
  expect(parseChatRefHref("file:Content/Verse/ledger.verse")).toEqual({
    kind: "file",
    id: "Content/Verse/ledger.verse",
  });
  expect(chatRefMarkdown("ledger.verse", "file:Content/Verse/ledger.verse")).toBe(
    "[/ledger.verse](file:Content/Verse/ledger.verse)",
  );
  expect(innerTextHit("Leaving Props unwired for the ledger", "props ledger")).toMatch(/Props/);
  expect(innerTextHit("nope", "props ledger")).toBeNull();
  expect(findChatRefTokens("see [@General Helper](ducky:abc) now")[0]).toMatchObject({
    label: "@General Helper",
    href: "ducky:abc",
  });
});

function ref(group: string, href: string, label: string): ChatRef {
  return { trigger: "@", id: href, label, group, href };
}

it("keeps other islands in their own mention group", () => {
  expect(chatMentionGroup("island", "island", "Roguelike")).toBe("This project");
  expect(chatMentionGroup("", "island", "")).toBe("Global");
  expect(chatMentionGroup("other", "island", "Arena")).toBe("Arena");
  expect(chatMentionGroup("other", "", "Arena")).toBe("Arena");
});

it("lists other projects before this project's duckies", () => {
  const ordered = orderChatMentions([
    ref("This project", "ducky:here", "Local"),
    ref("Arena", "ducky:there", "Remote"),
    ref("Global", "profile:verse-coder", "Verse Coder"),
  ]);
  expect(ordered.map((row) => row.group)).toEqual(["Arena", "This project", "Global"]);
});

it("opens ~ from the catalog before the workspace search returns", () => {
  const mentions = [ref("Arena", "ducky:there", "Remote")];
  const skills: ChatRef[] = [{ trigger: "/", id: "skill:verse", label: "Verse", group: "Skills", href: "skill:verse" }];
  const files: ChatRef[] = [{ trigger: "/", id: "file:Content/Verse/ledger.verse", label: "ledger.verse", group: "Content", href: "file:Content/Verse/ledger.verse" }];
  expect(instantInnerRefs("", mentions, skills, files).map((row) => row.href)).toEqual(["ducky:there", "skill:verse"]);
  expect(instantInnerRefs("ledger", mentions, skills, files)[0]?.href).toBe("file:Content/Verse/ledger.verse");
  const merged = mergeInnerRefs(instantInnerRefs("", mentions, skills, files), [
    { trigger: "~", id: "chat:there", label: "Remote", group: "Chats", href: "ducky:there", description: "inside the chat" },
  ]);
  expect(merged[0]).toMatchObject({ group: "Arena", description: "inside the chat", trigger: "~" });
});

it("deletes a chip as one unit when the selection only nicks it", () => {
  const text = "hi [@Animation Artist](profile:animation-artist) go";
  const token = findChatRefTokens(text)[0]!;
  const nicked = expandRangeToChips(text, token.start + 2, token.start + 5);
  expect(nicked).toEqual({ start: token.start, end: token.end });
  expect(chipTouchingCaret(text, token.end, "before")?.href).toBe("profile:animation-artist");
  expect(chipTouchingCaret(text, token.start, "after")?.href).toBe("profile:animation-artist");
  expect(chipTouchingCaret(text, 0, "before")).toBeNull();
});
