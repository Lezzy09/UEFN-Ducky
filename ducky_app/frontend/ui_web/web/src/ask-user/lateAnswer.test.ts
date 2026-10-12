// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ answer_late_question: vi.fn(async () => ({ ok: true })) }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));

import { _resetAskUserForTests, listAskUserSessions, markAskUserLate, runAskUser, settleAskUser } from "./runAskUser";

afterEach(() => {
  _resetAskUserForTests();
  vi.clearAllMocks();
});

const questions = [{ id: "path", prompt: "Where should proxies go?", options: [{ id: "local", label: "A local folder" }] }];

it("an answer given after the agent's turn ended reaches its chat as a message", async () => {
  // Oct 11 2026: a Codex lead's turn ended with its question card still open; the card said
  // "Agent paused until Submit" and an answer would have gone nowhere.
  const done = runAskUser(questions, "Proxy output path", "lead");
  markAskUserLate("lead");
  const [session] = listAskUserSessions();
  expect(session.late).toBe(true);
  settleAskUser({ ok: true, skipped_all: false, answers: { path: { selected: ["local"], text: "use api.local_dir", skipped: false } } }, session.id);
  await done;
  expect(api.answer_late_question).toHaveBeenCalledTimes(1);
  const [conv, text] = api.answer_late_question.mock.calls[0] as unknown as [string, string];
  expect(conv).toBe("lead");
  expect(text).toContain('"Proxy output path"');
  expect(text).toContain("A local folder; use api.local_dir");
});

it("an answer the agent is still waiting for is not sent twice", async () => {
  const done = runAskUser(questions, "t", "lead");
  markAskUserLate("other-chat");
  const [session] = listAskUserSessions();
  settleAskUser({ ok: true, skipped_all: false, answers: { path: { selected: ["local"], text: "", skipped: false } } }, session.id);
  await done;
  expect(api.answer_late_question).not.toHaveBeenCalled();
});
