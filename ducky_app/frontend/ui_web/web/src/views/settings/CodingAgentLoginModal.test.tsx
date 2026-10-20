// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  api: {
    coding_agent_login: vi.fn(),
    coding_agent_login_status: vi.fn(),
    copy_text: vi.fn(),
  },
}));

vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => fake.api, isRemote: () => true }));

import { CodingAgentLoginModal } from "./CodingAgentsSection";

afterEach(() => vi.clearAllMocks());

it("shows Codex's one-time code to type at the link, with no box to paste a code into", async () => {
  fake.api.coding_agent_login.mockResolvedValue({
    ok: true,
    login_ui: "device_code",
    auth_url: "https://auth.openai.com/codex/device",
    user_code: "ABCD-EFG12",
  });
  fake.api.coding_agent_login_status.mockResolvedValue({ ok: true, logged_in: false });
  const onLoggedIn = vi.fn();
  render(<CodingAgentLoginModal agentId="codex" title="Log in to Codex" onClose={() => {}} onLoggedIn={onLoggedIn} />);

  expect(await screen.findByText("ABCD-EFG12")).toBeTruthy();
  expect(screen.getByText("https://auth.openai.com/codex/device")).toBeTruthy();
  expect(screen.queryByPlaceholderText("Paste the login code")).toBeNull();
  fireEvent.click(screen.getByText("Copy code"));
  expect(fake.api.copy_text).toHaveBeenCalledWith("ABCD-EFG12");

  // Signed in on the phone: the poll sees it and the modal finishes by itself.
  fake.api.coding_agent_login_status.mockResolvedValue({ ok: true, logged_in: true });
  await waitFor(() => expect(onLoggedIn).toHaveBeenCalled(), { timeout: 3000 });
});
