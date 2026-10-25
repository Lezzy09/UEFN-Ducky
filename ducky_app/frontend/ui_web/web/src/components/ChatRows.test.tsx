// @vitest-environment jsdom
import { cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("./DuckyParade", () => ({ DuckyParadeOverlay: ({ label }: { label: string }) => <div>{label}</div> }));
vi.mock("./VirtualChatMessageList", () => ({ VirtualChatMessageList: () => <div>message list</div> }));
vi.mock("./ChatPaneEmptyState", () => ({ ChatPaneEmptyState: () => <div>empty chat</div> }));
import type { ChatMessage } from "../types/panel";
import { chatRunReducer, initialRunState } from "../hooks/chatRun/chatRunReducer";
import { ChatRows, useChatRowModel, type ChatRowsProps } from "./ChatRows";

const base = {
  chatId: "rows-chat",
  isFocus: false,
  isPopup: false,
  hydrated: true,
  loadError: null,
  messageCount: 0,
  onRetry: () => {},
  isEmpty: false,
  showEmptyState: false,
  emptyState: {},
  onZoomChange: () => {},
  listRef: null,
  list: {},
} as unknown as ChatRowsProps;

afterEach(cleanup);

it("shows Loading until the chat is loaded, then the list", () => {
  const { rerender } = render(<ChatRows {...base} hydrated={false} />);
  expect(screen.getByText("Loading")).toBeTruthy();
  rerender(<ChatRows {...base} />);
  expect(screen.getByText("message list")).toBeTruthy();
});

it("offers Retry on a load error and the empty state for an empty chat", () => {
  const onRetry = vi.fn();
  const { rerender } = render(<ChatRows {...base} loadError="Could not load" onRetry={onRetry} />);
  expect(screen.getByRole("alert").textContent).toContain("Could not load");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(onRetry).toHaveBeenCalledTimes(1);
  rerender(<ChatRows {...base} isEmpty showEmptyState />);
  expect(screen.getByText("empty chat")).toBeTruthy();
});

// Row ids are message index * 1000 + row index (chat_rows.ROW_ID_STEP), so they have gaps.
const gapped: ChatMessage[] = [
  { id: 3000, role: "user", text: "build it" },
  { id: 3001, role: "assistant", text: "on it" },
  { id: 4000, role: "user", text: "thanks" },
];

const rowModel = (messages: ChatMessage[]) =>
  renderHook(() =>
    useChatRowModel({ messages, agentRunning: false, activeRunId: null, streamBuffer: "", streamThinking: "" }),
  ).result.current;

it("ids 3000, 3001, 4000 render as three rows in order", () => {
  const { rows, editableRowId } = rowModel(gapped);
  expect(rows.map((r) => r.id)).toEqual(["3000", "3001", "4000"]);
  expect(editableRowId).toBe("4000");
});

it("loading the same gapped rows again keeps one row per id", () => {
  const once = chatRunReducer({ ...initialRunState }, { type: "loaded", rows: gapped });
  const twice = chatRunReducer(once, { type: "loaded", rows: gapped });
  expect(twice.messages.map((m) => m.id)).toEqual([3000, 3001, 4000]);
  expect(rowModel(twice.messages).rows).toHaveLength(3);
});
