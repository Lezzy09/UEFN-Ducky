// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../types/panel";

const api = {
  load_messages: vi.fn<(chatId: string) => Promise<ChatMessage[]>>(),
  list_running_agents: vi.fn<() => Promise<string[]>>(),
};
vi.mock("./usePanelApi", () => ({ getApi: () => api }));
vi.mock("./useAgentEventBus", () => ({ useAgentEventSubscription: () => {} }));

import { setCachedChatMessages } from "./chatMessagesCache";
import { useChatMessages } from "./useChatMessages";

/** The view a chat tab left behind when it went to the background mid-run. */
function cacheMidRun(chatId: string) {
  setCachedChatMessages(chatId, {
    messages: [
      { id: 1, role: "user", text: "build the demo" },
      { id: "opt-4", role: "tool", text: "", tool: { name: "save_workflow", arguments: {} } },
    ],
    streamBuffer: "Checking the final wiring",
    streamThinking: "",
    optimisticRunning: true,
    hasNewBelow: false,
    isAtBottom: true,
    activeRunId: "run-1",
    stoppedRun: false,
  });
}

const finalRows: ChatMessage[] = [
  { id: 1, role: "user", text: "build the demo" },
  { id: 2, role: "tool", text: "", tool: { name: "save_workflow", arguments: {} } },
  { id: 3, role: "assistant", text: "The demo workflow is saved and wired." },
];

describe("a chat tab reopened after it was in the background", () => {
  beforeEach(() => {
    api.load_messages.mockReset();
    api.list_running_agents.mockReset();
  });

  it("shows the finished run at once when the run ended while the tab was away", async () => {
    cacheMidRun("chat-done");
    api.list_running_agents.mockResolvedValue([]);
    api.load_messages.mockResolvedValue(finalRows);

    const { result } = renderHook(() => useChatMessages("chat-done", true, false));

    // Before: stuck on "Running tools…" until a 15 s reconcile timer fired.
    await waitFor(() => expect(result.current.agentRunning).toBe(false), { timeout: 1000 });
    await waitFor(() => expect(result.current.messages).toEqual(finalRows), { timeout: 1000 });
    expect(result.current.streamBuffer).toBe("");
  });

  it("stays live when the run is still going", async () => {
    cacheMidRun("chat-live");
    api.list_running_agents.mockResolvedValue(["chat-live"]);
    api.load_messages.mockResolvedValue(finalRows.slice(0, 2));

    const { result } = renderHook(() => useChatMessages("chat-live", true, true));

    await waitFor(() => expect(api.load_messages).toHaveBeenCalled(), { timeout: 1000 });
    expect(result.current.agentRunning).toBe(true);
  });
});
