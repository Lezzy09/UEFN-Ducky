// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ContextUsage } from "../types/panel";

const api = {
  get_context_usage: vi.fn(async () => ({ breakdown: [] })),
  set_agent_allow_everything: vi.fn(async () => ({ ok: true, on: false, own: false, from_title: "" })),
};
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("./ChangesetPanel", () => ({ ChangesetPanel: () => null }));

import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";
import { ContextUsagePanel } from "./ContextUsagePanel";

function usage(allow: { on: boolean; own: boolean; from_title?: string }): ContextUsage {
  return {
    used_tokens: 1000, context_limit: 200000, input_tokens: 0, breakdown: [],
    agent_info: { coding_agent: "claude_code", label: "Claude Code", model: "claude-opus-5-5", enabled: true, session_active: true,
                  num_turns: 1, context_tokens: 1000, has_run: true, permission_mode: "acceptEdits", allow_everything: allow },
  } as unknown as ContextUsage;
}

const show = (allow: { on: boolean; own: boolean; from_title?: string }) => render(
  <ConfirmModalProvider><ContextUsagePanel convId="c1" usage={usage(allow)} sessionFiles={[]} onClose={() => undefined} /></ConfirmModalProvider>,
);

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Approvals row", () => {
  it("shows Allow everything set in this chat and turns it off", async () => {
    show({ on: true, own: true });
    expect(screen.getByText("Allow everything (never asks)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(api.set_agent_allow_everything).toHaveBeenCalledWith("c1", false));
    await waitFor(() => expect(screen.queryByText("Approvals")).toBeNull());
  });

  it("names the chat it came from, without a switch here", () => {
    show({ on: true, own: false, from_title: "Card art lead" });
    expect(screen.getByText("Allow everything, from Card art lead")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
  });

  it("shows nothing while the chat asks", () => {
    show({ on: false, own: false });
    expect(screen.queryByText("Approvals")).toBeNull();
  });
});
