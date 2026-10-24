// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Every other bridge call answers empty (lists and loads [], everything else {}): the pane renders offline.
const overrides = vi.hoisted(() => ({
  get_models_catalog: async () => ({
    models: [{ id: "claude-opus-5-5", name: "Claude Opus", provider: "anthropic", provider_key: "anthropic" }],
    default_model: "claude-opus-5-5",
  }),
  get_key_status: async () => ({ anthropic: true }),
  send_message: (async () => ({ run_id: "r1" })) as (...args: unknown[]) => Promise<unknown>,
}));
const api = vi.hoisted(() => new Proxy({} as Record<string, unknown>, {
  get: (_t, key) => {
    if (key === "then") return undefined;
    if (key in overrides) return overrides[key as keyof typeof overrides];
    return async () => (/^(list|load)_/.test(String(key)) ? [] : {});
  },
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false, requireApi: () => api }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => null }));

import { ChatPane } from "./ChatPane";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import { loadModelsCatalog } from "../hooks/modelsCatalogCache";
import { SWARM_CARD_EVENT, swarmBuildPrompt } from "./tool-presenters/SwarmCard";
import type { ChatTab } from "../types/panel";

const chat = { id: "chat-swarm", name: "Lead", title: "Lead", codingAgent: "ducky", model: "claude-opus-5-5" } as unknown as ChatTab;

beforeEach(async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  await loadModelsCatalog({ force: true });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("a swarm card's Build sends its text and leaves the half-typed draft in the composer", async () => {
  const send = vi.fn(async () => ({ run_id: "r1" }));
  overrides.send_message = send;
  render(
    <ConfirmModalProvider>
      <ChatPane chat={chat} visible allChats={[chat]} onOpenChat={() => {}} isAgentRunning={false} />
    </ConfirmModalProvider>,
  );
  const box = screen.getByRole("textbox");
  box.focus();
  box.textContent = "also add a tester";
  fireEvent.input(box);
  await act(async () => {});

  // The card's own send: a bubbling event from inside the pane (useSwarmCardSend picks it up).
  const build = swarmBuildPrompt(3);
  await act(async () => {
    box.dispatchEvent(new CustomEvent(SWARM_CARD_EVENT, { detail: { action: "build", text: build }, bubbles: true }));
  });

  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  expect((send.mock.calls[0] as unknown[]).slice(0, 2)).toEqual(["chat-swarm", build]);
  expect(box.textContent).toBe("also add a tester");
});
