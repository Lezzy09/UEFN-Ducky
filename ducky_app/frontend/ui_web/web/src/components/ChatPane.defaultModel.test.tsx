// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const NO_MODEL = "This ducky has no model. Set a Default Model.";

// Every other bridge call answers empty (lists and loads [], everything else {}): the pane renders offline.
const overrides = vi.hoisted(() => ({
  adopt_default_model: (async () => ({})) as (...args: unknown[]) => Promise<unknown>,
  get_models_catalog: async () => ({
    models: [{ id: "claude-opus-5-5", name: "Claude Opus", provider: "anthropic", provider_key: "anthropic" }],
    default_model: "codex:gpt-6-astra",
  }),
  get_key_status: async () => ({ anthropic: true }),
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
import { pushLocalAgentEvent } from "../hooks/useAgentEventBus";
import type { ChatTab } from "../types/panel";

const chat = { id: "chat-1", name: "Builder", title: "Builder", codingAgent: "ducky", model: "" } as unknown as ChatTab;

function Pane({ tab = chat }: { tab?: ChatTab }) {
  return (
    <ConfirmModalProvider>
      <ChatPane chat={tab} visible allChats={[tab]} onOpenChat={() => {}} isAgentRunning={false} />
    </ConfirmModalProvider>
  );
}

beforeEach(async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  await loadModelsCatalog({ force: true });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("a Ducky chat with no model takes the Default Model instead of asking for one", async () => {
  const adopt = vi.fn(async () => ({ ok: true, coding_agent: "codex", model: "gpt-6-astra", provider: "" }));
  overrides.adopt_default_model = adopt;
  render(<Pane />);
  await act(async () => {});
  await waitFor(() => expect(adopt).toHaveBeenCalledWith("chat-1", false));
  await act(async () => {});
  expect(screen.queryByText(NO_MODEL)).toBeNull();
});

it("with no model to take, the chat asks for a pick in the composer, not Settings", async () => {
  // Oct 16 2026: the Default Model codex:gpt-6-astra left Codex's list; new duckies said
  // "Set a Default Model." and send opened Settings, so the chat stopped there.
  const why = "Your Default Model codex:gpt-6-astra isn't available. Pick a model below and this ducky uses it.";
  overrides.adopt_default_model = vi.fn(async () => ({ ok: false, error: why }));
  render(<Pane />);
  await waitFor(() => expect(screen.getByText(why)).toBeTruthy());
  expect(screen.queryByText(NO_MODEL)).toBeNull();
  expect(screen.getByTitle("Pick a model — your message sends then")).toBeTruthy();
});

it("says how many messages wait for a model", async () => {
  overrides.adopt_default_model = vi.fn(async () => ({ ok: false, error: "No Default Model is set.", held: 2 }));
  render(<Pane />);
  await waitFor(() => expect(screen.getByText("2 messages are waiting. Pick a model below and they run.")).toBeTruthy());
});

it("a chat that took Ducky AI says why, and runs what waited once it has a model", async () => {
  const note = "Your Default Model codex:gpt-6-astra isn't available, so this ducky uses Ducky AI. Pick another model below anytime.";
  overrides.adopt_default_model = vi.fn(async () => ({
    ok: true, coding_agent: "ducky", model: "ducky-brain", provider: "uefn_ducky", note,
  }));
  const runHeld = vi.fn(async () => ({ ok: true, ran: 1 }));
  (overrides as Record<string, unknown>).run_held_messages = runHeld;
  render(<Pane />);
  await waitFor(() => expect(screen.getByText(note)).toBeTruthy());
  // An agent's message reached the chat before its model was saved: it runs on this one.
  await act(async () => {
    pushLocalAgentEvent({ type: "model_needed", conv_id: "chat-1", held: 1, text: "No model." });
  });
  await waitFor(() => expect(runHeld).toHaveBeenCalledWith("chat-1", "ducky-brain", "ducky"));
  delete (overrides as Record<string, unknown>).run_held_messages;
});

it("text sent before the chat has a model sends itself once one is picked", async () => {
  overrides.adopt_default_model = vi.fn(async () => ({ ok: false, error: "No Default Model is set." }));
  const send = vi.fn(async () => ({ run_id: "r1" }));
  (overrides as Record<string, unknown>).send_message = send;
  render(<Pane tab={{ ...chat, id: "chat-2" } as ChatTab} />);
  await waitFor(() => expect(screen.getByText("No Default Model is set.")).toBeTruthy());
  const box = screen.getByRole("textbox");
  box.focus();
  box.textContent = "build the parser";
  fireEvent.input(box);
  await act(async () => {});
  fireEvent.click(screen.getByTitle("Pick a model — your message sends then"));
  await act(async () => {});
  expect(send).not.toHaveBeenCalled();
  expect(box.textContent).toBe("build the parser");
  // The person picks a model (here: Ducky gives the chat one).
  await act(async () => {
    pushLocalAgentEvent({ type: "model_adopted", conv_id: "chat-2", model: "claude-opus-5-5",
                          coding_agent: "ducky", provider: "anthropic", text: "" });
  });
  await waitFor(() => expect(send).toHaveBeenCalled());
  expect((send.mock.calls[0] as unknown[]).slice(0, 4)).toEqual(["chat-2", "build the parser", "agent", "claude-opus-5-5"]);
  delete (overrides as Record<string, unknown>).send_message;
});
