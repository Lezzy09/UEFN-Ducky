// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPermissionModeId, ChatPermissionsDto } from "../types/panel";

const TEXT: Record<ChatPermissionModeId, [string, string]> = {
  ask: ["Ask before changes", "Asks before editing files or running commands."],
  edits: ["Accept edits", "Edits files without asking. Asks before commands."],
  all: ["Allow everything", "Never asks in this chat or the agents it starts."],
};

function state(mode: ChatPermissionModeId, extra: Partial<ChatPermissionsDto> = {}, reason = ""): ChatPermissionsDto {
  return {
    mode,
    label: TEXT[mode][0],
    own: true,
    from_title: "",
    agent: "claude_code",
    agent_label: "Claude Code",
    asks: !reason,
    modes: (["ask", "edits", "all"] as ChatPermissionModeId[]).map((id) => ({
      id,
      label: TEXT[id][0],
      description: TEXT[id][1],
      available: !reason,
      reason,
    })),
    rules: [
      { rule: "Bash:git status", label: "Bash: git status" },
      { rule: "WebFetch", label: "WebFetch" },
    ],
    ...extra,
  };
}

const api = {
  get_agent_permissions: vi.fn(async () => state("edits")),
  set_agent_permission_mode: vi.fn(async (_c: string, mode: ChatPermissionModeId) => state(mode)),
  remove_agent_permission_rule: vi.fn(async () => state("edits", { rules: [{ rule: "WebFetch", label: "WebFetch" }] })),
  clear_agent_permission_rules: vi.fn(async () => state("edits", { rules: [] })),
};
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));

const { ChatPermissionsButton } = await import("./ChatPermissionsButton");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  api.get_agent_permissions.mockImplementation(async () => state("edits"));
});

async function openPopup(agent = "claude_code") {
  render(<ChatPermissionsButton convId="c1" codingAgent={agent} />);
  const button = await screen.findByRole("button", { name: "Permissions: Accept edits" });
  fireEvent.click(button);
  return screen.findByRole("menu", { name: "Permissions" });
}

const checked = () => screen.getAllByRole("menuitemradio").filter((el) => el.getAttribute("aria-checked") === "true");

describe("ChatPermissionsButton", () => {
  it("shows the chat's mode on hover and opens a list of modes with the active one checked", async () => {
    await openPopup();
    expect(api.get_agent_permissions).toHaveBeenCalledWith("c1", "claude_code");
    const names = screen.getAllByRole("menuitemradio").map((el) => el.getAttribute("aria-label"));
    expect(names).toEqual(["Ask before changes", "Accept edits", "Allow everything"]);
    expect(checked().map((el) => el.getAttribute("aria-label"))).toEqual(["Accept edits"]);
    expect(screen.getByText("Edits files without asking. Asks before commands.")).toBeTruthy();
    expect(screen.getByText("Bash: git status")).toBeTruthy();
  });

  it("picks a mode for this chat", async () => {
    await openPopup();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Ask before changes" }));
    await waitFor(() => expect(api.set_agent_permission_mode).toHaveBeenCalledWith("c1", "ask", "claude_code"));
    await waitFor(() => expect(checked().map((el) => el.getAttribute("aria-label"))).toEqual(["Ask before changes"]));
    expect(screen.getByRole("button", { name: "Permissions: Ask before changes" })).toBeTruthy();
  });

  it("picks a mode with its number key and closes on Escape", async () => {
    await openPopup();
    await act(async () => {
      fireEvent.keyDown(window, { key: "3" });
    });
    await waitFor(() => expect(api.set_agent_permission_mode).toHaveBeenCalledWith("c1", "all", "claude_code"));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  });

  it("removes one allowed rule and clears them all", async () => {
    await openPopup();
    fireEvent.click(screen.getByRole("button", { name: "Remove Bash: git status" }));
    await waitFor(() => expect(api.remove_agent_permission_rule).toHaveBeenCalledWith("c1", "Bash:git status", "claude_code"));
    await waitFor(() => expect(screen.queryByText("Bash: git status")).toBeNull());
    expect(screen.getByText("WebFetch")).toBeTruthy();

    api.remove_agent_permission_rule.mockClear();
    cleanup();
    await openPopup();
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(api.clear_agent_permission_rules).toHaveBeenCalledWith("c1", "claude_code"));
    await waitFor(() => expect(screen.getByText(/Nothing yet/)).toBeTruthy());
  });

  it("says what an agent that never asks does, with no modes to pick, and still lists what the chat allowed", async () => {
    const note = "Codex edits files and runs commands without asking. Ducky can't stop it to ask first.";
    api.get_agent_permissions.mockImplementation(async () =>
      state(
        "edits",
        { agent: "codex", agent_label: "Codex", note, hint: "To approve changes first, switch this chat to Ducky or Claude Code." },
        note,
      ),
    );
    render(<ChatPermissionsButton convId="c1" codingAgent="codex" />);
    fireEvent.click(await screen.findByRole("button", { name: "Permissions: Codex never asks" }));
    expect(screen.getByText(note)).toBeTruthy();
    expect(screen.getByText("To approve changes first, switch this chat to Ducky or Claude Code.")).toBeTruthy();
    // No mode is shown as ticked, because none of them applies to Codex.
    expect(screen.queryAllByRole("menuitemradio")).toHaveLength(0);
    // Its commands in a Ducky terminal still ask, so the chat's allowed list shows.
    expect(screen.getByText("Allowed in this chat")).toBeTruthy();
    fireEvent.keyDown(window, { key: "1" });
    expect(api.set_agent_permission_mode).not.toHaveBeenCalled();
  });

  it("names the old plugin on the mode it lacks and updates it from the Store in place", async () => {
    const reason = "Needs a newer Anthropic plugin (this PC has 1.0.54).";
    const old = state("all", { update: { plugin_id: "anthropic", label: "Anthropic", version: "1.0.54", from_store: true } });
    old.modes[0] = { ...old.modes[0], available: false, reason };
    api.get_agent_permissions.mockImplementation(async () => old);
    const fresh = state("all");
    const update = vi.fn(async () => fresh);
    Object.assign(api, { update_agent_plugin: update });
    render(<ChatPermissionsButton convId="c1" codingAgent="claude_code" />);
    fireEvent.click(await screen.findByRole("button", { name: "Permissions: Allow everything" }));
    const ask = screen.getByRole("menuitemradio", { name: "Ask before changes" }) as HTMLButtonElement;
    expect(ask.disabled).toBe(true);
    expect(screen.getByText(reason)).toBeTruthy();
    // After the update the new plugin honours Ask before changes.
    api.get_agent_permissions.mockImplementation(async () => fresh);
    fireEvent.click(screen.getByRole("button", { name: "Update Anthropic plugin" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("c1", "claude_code"));
    await waitFor(() =>
      expect((screen.getByRole("menuitemradio", { name: "Ask before changes" }) as HTMLButtonElement).disabled).toBe(false),
    );
    expect(screen.queryByRole("button", { name: "Update Anthropic plugin" })).toBeNull();
    delete (api as Record<string, unknown>).update_agent_plugin;
  });

  it("says a local copy of the plugin is not updated from the Store", async () => {
    const old = state("edits", { update: { plugin_id: "anthropic", label: "Anthropic", version: "1.0.54", from_store: false } });
    old.modes[0] = { ...old.modes[0], available: false, reason: "Needs a newer Anthropic plugin (this PC has 1.0.54)." };
    api.get_agent_permissions.mockImplementation(async () => old);
    await openPopup();
    expect(screen.getByText("Your Anthropic plugin is a local copy, so Store updates don't reach it.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Update Anthropic plugin" })).toBeNull();
  });
});
