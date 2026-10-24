import { afterEach, expect, it, vi } from "vitest";

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => null }));

import { _resetAskUserForTests, answerAskUserWithMessage, listAskUserSessions, runAskUser } from "./runAskUser";

afterEach(() => _resetAskUserForTests());

it("a typed message answers the chat's open question once, as free text on every question", async () => {
  const pending = runAskUser(
    [
      { id: "path", prompt: "Which path?", options: [{ id: "a", label: "A" }, { id: "b", label: "B" }], allow_free_text: false },
      { id: "notes", prompt: "Anything else?" },
    ],
    "",
    "chat-1",
  );
  expect(answerAskUserWithMessage("chat-1", "  use option B ")).toBe(true);
  await expect(pending).resolves.toEqual({
    ok: true,
    skipped_all: false,
    free_text: "use option B",
    answers: {
      path: { selected: [], text: "use option B", skipped: false },
      notes: { selected: [], text: "use option B", skipped: false },
    },
  });
  expect(listAskUserSessions()).toEqual([]);
  // Answered: the next message goes the usual way (steer / queue).
  expect(answerAskUserWithMessage("chat-1", "and also this")).toBe(false);
});

it("no open question in this chat, or an empty message: not answered here", () => {
  void runAskUser([{ id: "q", prompt: "Other chat?" }], "", "chat-2");
  expect(answerAskUserWithMessage("chat-1", "hello")).toBe(false);
  expect(answerAskUserWithMessage("chat-2", "   ")).toBe(false);
  expect(listAskUserSessions()).toHaveLength(1);
});
