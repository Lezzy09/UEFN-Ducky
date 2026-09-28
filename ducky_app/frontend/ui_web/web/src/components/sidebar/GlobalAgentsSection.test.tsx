// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConfirmModalProvider } from "../../contexts/ConfirmModalContext";
import { onDuckyProfileChanged } from "../../navigation/duckyProfileChanged";
import type { AgentProfileDto } from "../../types/panel";
import { GlobalAgentsSection } from "./GlobalAgentsSection";

const api = vi.hoisted(() => ({
  list_agent_profiles: vi.fn(), save_agent_profile: vi.fn(),
  save_agent_profile_override: vi.fn(), delete_agent_profile: vi.fn(),
  create_conversation: vi.fn(),
}));
vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("../ducky/DuckyAvatars", () => ({ DuckyAvatar: () => null, DUCKY_AVATAR_SIZES: { sidebar: 22 } }));

const bundled: AgentProfileDto = {
  id: "verse-coder", name: "Verse Coder", kind: "bundled", ducky_style: "coder",
  ducky_personality: "Code carefully", disabled_packs: [], disabled_tool_ids: [],
};
const custom: AgentProfileDto = {
  ...bundled, id: "my-agent", kind: "custom", name: "My Agent", when_to_use: "Help me build",
  disabled_packs: ["art"], disabled_tool_ids: ["delete"], favorite_models: ["model"],
};
let profiles: AgentProfileDto[];
const opened = vi.fn();
const created = vi.fn();
function mount() {
  return render(<ConfirmModalProvider><GlobalAgentsSection folders={[]} rootChats={[]} projectSlug="island" compact filterQuery="" activeChats={[]} onOpenChat={opened} onCreated={created} /></ConfirmModalProvider>);
}
function row(name: string) { return screen.getByRole("button", { name, exact: true }); }
async function rename(name: string) {
  fireEvent.click(within(await screen.findByRole("button", { name, exact: true })).getByTitle("Rename"));
  return screen.getByRole("textbox", { name: `Rename ${name}` });
}

beforeEach(() => {
  profiles = [structuredClone(bundled), structuredClone(custom)];
  api.list_agent_profiles.mockImplementation(async () => ({ profiles: [...profiles] }));
  api.save_agent_profile_override.mockImplementation(async (id, patch) => {
    const saved = { ...profiles.find((item) => item.id === id)!, ...patch };
    profiles = profiles.map((item) => item.id === id ? saved : item);
    return { ok: true, profile: saved };
  });
  api.save_agent_profile.mockImplementation(async (saved) => {
    profiles = profiles.map((item) => item.id === saved.id ? saved : item);
    return { ok: true, profile: saved };
  });
  api.delete_agent_profile.mockImplementation(async (id) => {
    profiles = profiles.filter((item) => item.id !== id);
    return { ok: true };
  });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("global agent sidebar actions", () => {
  it("renames a bundled profile inline, announces the change, and persists on remount", async () => {
    const changed = vi.fn();
    const off = onDuckyProfileChanged(changed);
    const view = mount();
    try {
      const input = await rename("Verse Coder");
      expect(document.activeElement).toBe(input);
      expect((input as HTMLInputElement).selectionEnd).toBe("Verse Coder".length);
      fireEvent.change(input, { target: { value: "  Verse Helper  " } });
      fireEvent.keyDown(input, { key: " " });
      fireEvent.keyDown(input, { key: "Enter" });
      fireEvent.blur(input);
      await screen.findByRole("button", { name: "Verse Helper", exact: true });
      expect(api.save_agent_profile_override).toHaveBeenCalledExactlyOnceWith("verse-coder", { name: "Verse Helper" });
      expect(api.save_agent_profile).not.toHaveBeenCalled();
      expect(api.create_conversation).not.toHaveBeenCalled();
      expect(opened).not.toHaveBeenCalled();
      expect(changed).toHaveBeenCalledWith(expect.objectContaining({ type: "saved", profileId: "verse-coder", name: "Verse Helper" }));
      view.unmount();
      mount();
      await screen.findByRole("button", { name: "Verse Helper", exact: true });
    } finally { off(); }
  });

  it("saves a custom name on blur without losing its settings", async () => {
    mount();
    const input = await rename("My Agent");
    fireEvent.change(input, { target: { value: "Island Helper" } });
    fireEvent.blur(input);
    await screen.findByRole("button", { name: "Island Helper", exact: true });
    expect(api.save_agent_profile).toHaveBeenCalledExactlyOnceWith({ ...custom, name: "Island Helper" });
    expect(api.save_agent_profile_override).not.toHaveBeenCalled();
  });

  it.each(["Escape", "empty", "unchanged"])("does not save a cancelled or invalid rename: %s", async (mode) => {
    mount();
    const input = await rename("Verse Coder");
    fireEvent.change(input, { target: { value: mode === "empty" ? "   " : mode === "unchanged" ? "Verse Coder" : "Discard me" } });
    fireEvent.keyDown(input, { key: mode === "Escape" ? "Escape" : "Enter" });
    fireEvent.blur(input);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(row("Verse Coder")).toBeTruthy();
    expect(api.save_agent_profile_override).not.toHaveBeenCalled();
    expect(api.create_conversation).not.toHaveBeenCalled();
  });

  it("offers rename and delete in the context menu and supports F2", async () => {
    mount();
    const agent = await screen.findByRole("button", { name: "Verse Coder", exact: true });
    fireEvent.contextMenu(agent, { clientX: 20, clientY: 20 });
    expect(screen.getByRole("menuitem", { name: "Delete" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    fireEvent.keyDown(agent, { key: "F2" });
    expect(screen.getByRole("textbox", { name: "Rename Verse Coder" })).toBeTruthy();
    expect(api.create_conversation).not.toHaveBeenCalled();
  });

  it("does not activate the row when using a hover action with the keyboard", async () => {
    mount();
    const agent = await screen.findByRole("button", { name: "Verse Coder", exact: true });
    const button = within(agent).getByTitle("Rename");
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.click(button);
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(api.create_conversation).not.toHaveBeenCalled();
  });

  it.each(["Verse Coder", "My Agent"])("confirms deletion of %s, refreshes the list, and persists on remount", async (name) => {
    const changed = vi.fn();
    const off = onDuckyProfileChanged(changed);
    const view = mount();
    try {
      const agent = await screen.findByRole("button", { name, exact: true });
      fireEvent.click(within(agent).getByTitle("Delete"));
      expect(api.delete_agent_profile).not.toHaveBeenCalled();
      expect(screen.getByText(/Existing chats will be kept/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Delete (D)" }));
      await waitFor(() => expect(screen.queryByRole("button", { name, exact: true })).toBeNull());
      const id = name === "Verse Coder" ? bundled.id : custom.id;
      expect(api.delete_agent_profile).toHaveBeenCalledExactlyOnceWith(id);
      expect(changed).toHaveBeenCalledWith({ type: "deleted", profileId: id });
      expect(api.create_conversation).not.toHaveBeenCalled();
      view.unmount();
      mount();
      await screen.findByRole("button", { name: name === "Verse Coder" ? "My Agent" : "Verse Coder", exact: true });
      expect(screen.queryByRole("button", { name, exact: true })).toBeNull();
    } finally { off(); }
  });

  it("keeps an agent when deletion is cancelled", async () => {
    mount();
    const agent = await screen.findByRole("button", { name: "Verse Coder", exact: true });
    fireEvent.keyDown(agent, { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel (C)" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(row("Verse Coder")).toBeTruthy();
    expect(api.delete_agent_profile).not.toHaveBeenCalled();
  });

  it("keeps the old name and reports a failed save", async () => {
    api.save_agent_profile_override.mockRejectedValueOnce(new Error("Storage unavailable"));
    mount();
    const input = await rename("Verse Coder");
    fireEvent.change(input, { target: { value: "New name" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("Storage unavailable");
    expect(row("Verse Coder")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New name", exact: true })).toBeNull();
  });

  it("keeps the row and reports deletion refused by the backend", async () => {
    api.delete_agent_profile.mockResolvedValueOnce({ ok: false });
    mount();
    fireEvent.keyDown(await screen.findByRole("button", { name: "Verse Coder", exact: true }), { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Delete (D)" }));
    await screen.findByText("The agent could not be deleted. Please try again.");
    expect(row("Verse Coder")).toBeTruthy();
  });
});
