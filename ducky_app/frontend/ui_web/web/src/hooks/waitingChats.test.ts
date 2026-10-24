// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetAskUserForTests, listAskUserSessions, runAskUser, settleAskUser } from "../ask-user/runAskUser";
import { _resetFocusedChatForAsk } from "../ask-user/focusedChatForAsk";
import { registerOpenChatReference } from "../navigation/openChatReference";
import { subscribePendingCard } from "../navigation/pendingCard";
import { _resetTerminalApprovalsForTests } from "../terminal/terminalApprovals";
import { pushLocalAgentEvent } from "./useAgentEventBus";
import {
  _resetWaitingChatsForTests,
  isChatWaiting,
  listWaitingItems,
  openWaitingChat,
  subscribeWaitingChats,
  useNeedsYou,
  waitingChatIds,
} from "./waitingChats";

const api = vi.hoisted(() => ({ terminal_pending_commands: vi.fn(async () => []) }));
vi.mock("./usePanelApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./usePanelApi")>()),
  getApi: () => api,
}));

const question = [{ id: "q", prompt: "Which map?", options: [{ id: "a", label: "A" }] }];
const command = (request_id: string, conv_id: string, cmd = "npm test") => ({
  type: "terminal_command_pending" as const,
  request_id,
  session_id: "s1",
  command: cmd,
  conv_id,
});

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
}

let changes = 0;
let stop: () => void = () => {};

beforeEach(() => {
  changes = 0;
  stop = subscribeWaitingChats(() => { changes += 1; });
});

afterEach(() => {
  stop();
  _resetAskUserForTests();
  _resetTerminalApprovalsForTests();
  _resetWaitingChatsForTests();
  _resetFocusedChatForAsk();
});

describe("chats waiting on the user", () => {
  it("a team member's command also marks its lead's chat as waiting", async () => {
    act(() => pushLocalAgentEvent({ ...command("r7", "member"), lead_conv_id: "lead", asked_by: "Verse Coder" }));
    await flush();
    expect([...waitingChatIds()].sort()).toEqual(["lead", "member"]);
    expect(listWaitingItems()[0].alsoIn).toEqual(["lead"]);
  });

  it("knows several chats at once and clears each one as soon as its card is answered", async () => {
    void runAskUser(question, "", "c1");
    act(() => {
      pushLocalAgentEvent(command("r2", "c2"));
      pushLocalAgentEvent(command("r3", "c3", "npm run build"));
    });
    await flush();
    expect([...waitingChatIds()].sort()).toEqual(["c1", "c2", "c3"]);
    expect(listWaitingItems().map((item) => [item.kind, item.convId, item.text])).toEqual([
      ["question", "c1", "Which map?"],
      ["command", "c2", "npm test"],
      ["command", "c3", "npm run build"],
    ]);

    // Answered in this window.
    const ask = listAskUserSessions()[0];
    act(() => settleAskUser({ ok: true, answers: { q: { selected: ["a"], text: "", skipped: false } } }, ask.id));
    expect(isChatWaiting("c1")).toBe(false);

    // Answered in another window: the backend's decided event.
    act(() => pushLocalAgentEvent({ type: "terminal_command_decided", request_id: "r2", conv_id: "c2" }));
    await flush();
    expect(isChatWaiting("c2")).toBe(false);
    expect(isChatWaiting("c3")).toBe(true);
    expect(changes).toBeGreaterThanOrEqual(3);
  });

  it("marks the group hub that shows a member's question too", () => {
    void runAskUser(question, "", "member", { groupIds: ["hub"] });
    expect(isChatWaiting("member")).toBe(true);
    expect(isChatWaiting("hub")).toBe(true);
  });

  it("lists a question no chat owns without marking any chat", () => {
    void runAskUser(question, "", "");
    expect(listWaitingItems()).toHaveLength(1);
    expect(listWaitingItems()[0].convId).toBe("");
    expect(waitingChatIds().size).toBe(0);
  });

  it("useNeedsYou gives a row the card kind and seconds waited, and clears when answered", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2026-10-24T12:00:00Z"));
      void runAskUser(question, "", "Stub 07", { groupIds: ["hub"] });
      act(() => pushLocalAgentEvent(command("r8", "Stub 08")));
      await flush();
      vi.setSystemTime(new Date("2026-10-24T12:01:02Z"));

      const stub7 = renderHook(() => useNeedsYou("Stub 07"));
      const hub = renderHook(() => useNeedsYou("hub"));
      const stub8 = renderHook(() => useNeedsYou("Stub 08"));
      const idle = renderHook(() => useNeedsYou("Stub 09"));
      expect(stub7.result.current).toEqual({ kind: "question", since: 62 });
      expect(hub.result.current?.kind).toBe("question");
      expect(stub8.result.current?.kind).toBe("command");
      expect(idle.result.current).toBeNull();

      // Another chat's card changing does not hand this row a new object.
      const before = stub7.result.current;
      act(() => pushLocalAgentEvent({ type: "terminal_command_decided", request_id: "r8", conv_id: "Stub 08" }));
      await flush();
      expect(stub8.result.current).toBeNull();
      expect(stub7.result.current).toBe(before);

      const ask = listAskUserSessions()[0];
      act(() => settleAskUser({ ok: true, answers: { q: { selected: ["a"], text: "", skipped: false } } }, ask.id));
      expect(stub7.result.current).toBeNull();
      expect(hub.result.current).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens the chat and asks it to scroll to the card", () => {
    const opened: string[] = [];
    const unregister = registerOpenChatReference((chat) => opened.push(chat.id));
    const scrolled: string[] = [];
    const unsubscribe = subscribePendingCard("c9", () => scrolled.push("c9"));
    try {
      expect(openWaitingChat("c9", "Builder")).toBe(true);
      expect(opened).toEqual(["c9"]);
      expect(scrolled).toEqual(["c9"]);
    } finally {
      unsubscribe();
      unregister();
    }
  });
});
