// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ load_messages: vi.fn() }));
vi.mock("./usePanelApi", () => ({ getApi: () => api }));

import { fetchChatRows } from "./chatRowsFetch";

afterEach(() => vi.resetAllMocks());

it("a load that answers with nothing fails instead of handing the chat an undefined list", async () => {
  // Oct 11 2026: the phone app crashed opening a chat ("reading 'length'"): the remote
  // bridge answers a 502 or a dropped connection with undefined.
  api.load_messages.mockResolvedValue(undefined);
  await expect(fetchChatRows("chat-1")).rejects.toThrow("no messages came back");
  api.load_messages.mockResolvedValue([{ id: 1, role: "user", text: "hi" }]);
  await expect(fetchChatRows("chat-1")).resolves.toHaveLength(1);
});
