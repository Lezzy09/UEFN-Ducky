// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const opened: Array<[string, string]> = [];
const titles: Record<string, string> = { known: "Bob PR review" };

vi.mock("../hooks/waitingChats", () => ({
  useWaitingItems: () => [
    { key: "a", convId: "known", kind: "question", text: "Allow?", id: "q1" },
    { key: "b", convId: "new-workflow-chat", kind: "question", text: "Allow?", id: "q2" },
  ],
  openWaitingChat: (id: string, name = "") => { opened.push([id, name]); return true; },
}));
vi.mock("../hooks/agentBackgroundActivity", () => ({ chatTitleFor: (id: string) => titles[id] || "" }));

import { WaitingForYouSection } from "./WaitingForYouSection";

afterEach(() => { cleanup(); opened.length = 0; });

describe("WaitingForYouSection", () => {
  it("never names a tab 'A chat': an unlisted chat opens untitled so its tab shows its own title", () => {
    render(<WaitingForYouSection onOpenChat={() => {}} />);
    fireEvent.click(screen.getByText("Bob PR review"));
    fireEvent.click(screen.getByText("A chat"));
    expect(opened).toEqual([["known", "Bob PR review"], ["new-workflow-chat", ""]]);
  });
});
