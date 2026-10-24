// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatTab } from "../types/panel";

// group_members is counted; every other panel call answers with an empty list.
const groupMembers = vi.hoisted(() => vi.fn(async () => ({ ok: true, members: [], leader_conv_id: "" })));
const api = vi.hoisted(() => new Proxy({}, {
  get: (_target, prop) => (prop === "then" ? undefined : prop === "group_members" ? groupMembers : () => Promise.resolve([])),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false, isPanelApiReady: () => true }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => null }));
vi.mock("./VirtualChatMessageList", () => ({ VirtualChatMessageList: () => null }));
vi.mock("./GroupMemberStrip", () => ({ GroupMemberStrip: () => null }));
vi.mock("../voice/VoiceControls", () => ({ VoiceControls: () => null }));
vi.mock("../voice/VoiceOverlay", () => ({ VoiceOverlay: () => null }));
vi.mock("./ModelSelector", () => ({ ModelSelector: () => null }));
vi.mock("./DuckyParade", () => ({ DuckyParadeOverlay: () => null }));

import { ChatPane } from "./ChatPane";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import { resetRosterStore } from "./team/rosterStore";

const group = { id: "team-1", name: "Team", isGroup: true } as ChatTab;

const show = () => render(
  <ConfirmModalProvider>
    <ChatPane chat={group} visible={false} allChats={[group]} onOpenChat={() => {}} isAgentRunning={false} />
  </ConfirmModalProvider>,
);

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  resetRosterStore();
  groupMembers.mockClear();
  vi.unstubAllGlobals();
});

it("opening the same team chat twice reads its roster once", async () => {
  const first = show();
  await act(async () => {});
  expect(groupMembers).toHaveBeenCalledTimes(1);
  first.unmount();

  show();
  await act(async () => {});
  expect(groupMembers).toHaveBeenCalledTimes(1);
});
