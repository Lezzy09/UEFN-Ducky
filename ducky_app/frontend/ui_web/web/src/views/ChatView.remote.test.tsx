// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

vi.mock("../plugin-ui", async (orig) => ({
  ...(await orig<typeof import("../plugin-ui")>()),
  shouldSuppressRemoteChatOpen: (conv: { title: string }) => conv.title === "Duck-Tac-Toe",
}));

import type { ChatTab } from "../types/panel";
import { shouldOpenRemoteConversation } from "./ChatView";

const member = { id: "m1", name: "Stub 01", parentConvId: "engine-hub" } as unknown as ChatTab;

describe("remote conversation events", () => {
  it("a member in a collapsed folder opens nothing; a new top-level chat opens its tab", () => {
    expect(shouldOpenRemoteConversation({ id: "m1", title: "Stub 01", folder_id: "engine" }, [member])).toBe(false);
    expect(shouldOpenRemoteConversation({ id: "new", title: "New chat", folder_id: "engine" }, [member])).toBe(true);
    expect(shouldOpenRemoteConversation({ id: "g", title: "Duck-Tac-Toe" }, [])).toBe(false);
  });

  it("the handler never expands a folder (the collapsed group stays shut)", () => {
    const src = readFileSync(resolve(process.cwd(), "src/views/ChatView.tsx"), "utf8");
    const handler = src.slice(src.indexOf("const handleRemoteConversation"), src.indexOf("useChatsChanged(load"));
    expect(handler).not.toMatch(/setFolders|expanded|expandFolder/);
    expect(src).not.toContain("expandFolder");
  });
});
