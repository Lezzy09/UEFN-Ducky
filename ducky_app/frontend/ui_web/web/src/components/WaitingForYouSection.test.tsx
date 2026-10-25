// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const opened: Array<[string, string]> = [];
let chats: Array<{ id: string; title: string; folder_id?: string; parent_conv_id?: string; is_group?: boolean }> = [];
const listAll = vi.fn(async () => chats);

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => ({ list_all_conversations: listAll }) }));
vi.mock("../hooks/waitingChats", () => ({
  useWaitingItems: () => [
    { key: "a", convId: "known", kind: "question", text: "Allow?", id: "q1" },
    { key: "b", convId: "member", kind: "question", text: "Allow web search in this chat?", id: "q2" },
  ],
  openWaitingChat: (id: string, name = "") => { opened.push([id, name]); return true; },
}));

import { loadChatTitles } from "../hooks/agentBackgroundActivity";
import { WaitingForYouSection } from "./WaitingForYouSection";

afterEach(() => { cleanup(); opened.length = 0; listAll.mockClear(); });

describe("WaitingForYouSection", () => {
  it("never names a tab 'A chat': an unlisted chat opens untitled so its tab shows its own title", async () => {
    chats = [{ id: "known", title: "Bob PR review" }];
    await loadChatTitles();
    render(<WaitingForYouSection onOpenChat={() => {}} />);
    await act(async () => {});
    fireEvent.click(screen.getByText("Bob PR review"));
    fireEvent.click(screen.getByText("A chat"));
    expect(opened).toEqual([["known", "Bob PR review"], ["member", ""]]);
  });

  it("loads a chat the tray never listed and names it with its group", async () => {
    chats = [{ id: "known", title: "Bob PR review" }];
    await loadChatTitles();
    // Made since the tray last read the list: a member of an archived team.
    chats = [...chats,
      { id: "hub", title: "Feedback → staff roadmap", is_group: true, folder_id: "archive" },
      { id: "member", title: "Developer 2", folder_id: "archive", parent_conv_id: "hub" }];
    listAll.mockClear();
    render(<WaitingForYouSection onOpenChat={() => {}} />);
    await act(async () => {});
    expect(listAll).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Feedback → staff roadmap · Developer 2 (archived)")).toBeTruthy();
    expect(screen.queryByText("A chat")).toBeNull();
  });
});
