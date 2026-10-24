// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EditorLayoutState, EditorTab } from "../types/panel";
import {
  decodeFocusParam,
  focusActivateNeedsOpen,
  focusIdToEditorTab,
  parseFocusId,
} from "./useFocusWindow";

const api = vi.hoisted(() => ({ set_visible_chats: vi.fn(async () => true), get_restore_tabs: vi.fn() }));
vi.mock("./usePanelApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./usePanelApi")>()),
  getApi: () => api,
}));

const {
  _resetVisibleChatsForTests,
  reportVisibleChats,
  restoreTabsAfterCrash,
  useReportVisibleChats,
  visibleChatIds,
} = await import("./useFocusWindowTabs");

const chat = (id: string): EditorTab => ({ id: `chat:${id}`, kind: "chat", name: id, chatId: id });
const file: EditorTab = { id: "file:a.verse", kind: "file", name: "a.verse", path: "a.verse" };
const tabs = [chat("450a3ccd"), chat("80fcc09e"), chat("c3"), file];
const layoutOf = (left: string, right?: string): EditorLayoutState => ({
  root: right
    ? { type: "split", direction: "row", children: [{ type: "group", groupId: "l" }, { type: "group", groupId: "r" }] }
    : { type: "group", groupId: "l" },
  groups: {
    l: { id: "l", tabIds: tabs.map((t) => t.id), activeTabId: left },
    ...(right ? { r: { id: "r", tabIds: [right], activeTabId: right } } : {}),
  },
  focusedGroupId: "l",
} as unknown as EditorLayoutState);

describe("visible chats", () => {
  beforeEach(() => {
    _resetVisibleChatsForTests();
    api.set_visible_chats.mockClear();
  });

  it("two panes with a chat each report both, once", () => {
    expect(visibleChatIds(layoutOf("chat:450a3ccd", "chat:80fcc09e"), tabs)).toEqual(["450a3ccd", "80fcc09e"]);
    expect(visibleChatIds(layoutOf("file:a.verse"), tabs)).toEqual([]);
    const { rerender } = renderHook(({ layout }) => useReportVisibleChats(layout, tabs, "main"), {
      initialProps: { layout: layoutOf("chat:450a3ccd", "chat:80fcc09e") },
    });
    expect(api.set_visible_chats).toHaveBeenCalledTimes(1);
    expect(api.set_visible_chats).toHaveBeenLastCalledWith(["450a3ccd", "80fcc09e"], "main");

    // Re-render with the same set (a new layout object, same active chats): no call.
    rerender({ layout: layoutOf("chat:450a3ccd", "chat:80fcc09e") });
    rerender({ layout: layoutOf("chat:450a3ccd", "chat:80fcc09e") });
    expect(api.set_visible_chats).toHaveBeenCalledTimes(1);

    // Switching tabs: one call with the new set.
    rerender({ layout: layoutOf("chat:c3", "chat:80fcc09e") });
    expect(api.set_visible_chats).toHaveBeenCalledTimes(2);
    expect(api.set_visible_chats).toHaveBeenLastCalledWith(["80fcc09e", "c3"], "main");
  });

  it("a hidden window shows no chats; showing it again sends the set back", () => {
    reportVisibleChats(["c3"], "main");
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(api.set_visible_chats).toHaveBeenLastCalledWith([], "main");
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(api.set_visible_chats).toHaveBeenLastCalledWith(["c3"], "main");
    expect(api.set_visible_chats).toHaveBeenCalledTimes(3);
    hidden.mockRestore();
  });

  it("each viewer (phone, remote) keeps its own set", () => {
    reportVisibleChats(["a"], "main");
    reportVisibleChats(["a"], "phone-1");
    reportVisibleChats(["a"], "main");
    expect(api.set_visible_chats.mock.calls).toEqual([[["a"], "main"], [["a"], "phone-1"]]);
  });
});

describe("restore tabs after a crash reload", () => {
  afterEach(() => api.get_restore_tabs.mockReset());

  it("opens every tab it had, in order", async () => {
    api.get_restore_tabs.mockResolvedValue(["chat:a", "chat:b"]);
    const opened: string[] = [];
    expect(await restoreTabsAfterCrash((id) => opened.push(id), "main")).toEqual(["chat:a", "chat:b"]);
    expect(opened).toEqual(["chat:a", "chat:b"]);
    expect(api.get_restore_tabs).toHaveBeenCalledWith("main");
  });

  it("does nothing on a normal load or when the call fails", async () => {
    const opened: string[] = [];
    api.get_restore_tabs.mockResolvedValue([]);
    expect(await restoreTabsAfterCrash((id) => opened.push(id))).toEqual([]);
    api.get_restore_tabs.mockRejectedValue(new Error("bridge down"));
    expect(await restoreTabsAfterCrash((id) => opened.push(id))).toEqual([]);
    expect(opened).toEqual([]);
  });
});

describe("focusActivateNeedsOpen", () => {
  it("re-opens when the tab is missing from React openTabs", () => {
    expect(focusActivateNeedsOpen(["chat:other"], "chat:ghost")).toBe(true);
    expect(focusActivateNeedsOpen([], "file:/a.verse")).toBe(true);
  });

  it("only activates when the tab is already open", () => {
    expect(focusActivateNeedsOpen(["chat:live", "file:/a.verse"], "chat:live")).toBe(false);
  });

  it("ignores empty focus ids", () => {
    expect(focusActivateNeedsOpen([], "")).toBe(false);
  });
});

describe("decodeFocusParam", () => {
  it("decodes a once-encoded settings id left by WebView2", () => {
    expect(decodeFocusParam("settings%3Amain")).toBe("settings:main");
  });

  it("is a no-op for already-decoded ids", () => {
    expect(decodeFocusParam("settings:main")).toBe("settings:main");
    expect(decodeFocusParam("chat:abc")).toBe("chat:abc");
  });

  it("unwraps a double-encoded colon", () => {
    expect(decodeFocusParam("settings%253Amain")).toBe("settings:main");
  });
});

describe("parseFocusId / focusIdToEditorTab", () => {
  it("accepts settings even when the URL param is still percent-encoded", () => {
    expect(parseFocusId("settings%3Amain")).toEqual({ kind: "settings" });
    expect(focusIdToEditorTab("settings%3Amain", "Settings")).toEqual({
      id: "settings:main",
      kind: "settings",
      name: "Settings",
    });
  });

  it("parses plan / plugin / verse-translated birth tabs", () => {
    expect(parseFocusId("plan:chat-1")).toEqual({ kind: "plan", chatId: "chat-1" });
    expect(parseFocusId("plugin:anim:panel")).toEqual({
      kind: "plugin",
      tabId: "plugin:anim:panel",
      pluginId: "anim",
      panelId: "panel",
    });
    expect(parseFocusId("verse-translated:es:content/foo.verse")).toEqual({
      kind: "verse-translated",
      lang: "es",
      path: "content/foo.verse",
    });
  });

  it("parses the Workflows singleton tab, and the old Automations and Pipelines ids as it", () => {
    for (const id of ["workflows:main", "automations:main", "pipelines:main"]) {
      expect(parseFocusId(id)).toEqual({ kind: "workflows" });
      expect(focusIdToEditorTab(id, "Old name")).toEqual({ id: "workflows:main", kind: "workflows", name: "Workflows" });
    }
  });

  it("parses ducky-profile pop-out tabs", () => {
    expect(parseFocusId("ducky-profile:audio")).toEqual({
      kind: "ducky-profile",
      profileId: "audio",
    });
    expect(focusIdToEditorTab("ducky-profile:audio", "Audio")).toEqual({
      id: "ducky-profile:audio",
      kind: "ducky-profile",
      name: "Audio",
      path: "audio",
    });
  });
});
