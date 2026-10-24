// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("./DuckyParade", () => ({ DuckyParadeOverlay: ({ label }: { label: string }) => <div>{label}</div> }));
vi.mock("./VirtualChatMessageList", () => ({ VirtualChatMessageList: () => <div>message list</div> }));
vi.mock("./ChatPaneEmptyState", () => ({ ChatPaneEmptyState: () => <div>empty chat</div> }));
import { ChatRows, type ChatRowsProps } from "./ChatRows";

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
