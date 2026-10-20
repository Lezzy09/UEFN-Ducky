// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { PluginLlmProvider } from "../hooks/usePluginContributions";

const nav = vi.hoisted(() => ({
  openLlmsProviderSettings: vi.fn(),
  openDefaultModelSettings: vi.fn(),
  openGatewaySetup: vi.fn(() => true),
}));
vi.mock("../navigation/openSettingsTab", () => ({
  openLlmsProviderSettings: nav.openLlmsProviderSettings,
  openDefaultModelSettings: nav.openDefaultModelSettings,
}));
vi.mock("./GatewaySetupNotice", () => ({ openGatewaySetup: nav.openGatewaySetup }));

import { ModelSetupNotice } from "./ModelSetupNotice";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const gateway = (id: string, label: string, chat?: boolean) => ({ id, label, chat }) as PluginLlmProvider;

it("with no AI at all, offers to set one up", () => {
  render(<ModelSetupNotice state={{ kind: "no_ai", gateways: [] }} onPickModel={() => {}} />);
  fireEvent.click(screen.getByText("Set up an AI"));
  expect(nav.openGatewaySetup).toHaveBeenCalled();
});

it("with AI services installed but none connected, links each one's settings", () => {
  const gateways = [gateway("anthropic", "Anthropic"), gateway("openai", "OpenAI"), gateway("tts", "Voices", false)];
  render(<ModelSetupNotice state={{ kind: "no_ai", gateways }} onPickModel={() => {}} />);
  fireEvent.click(screen.getByText("Connect OpenAI"));
  expect(nav.openLlmsProviderSettings).toHaveBeenCalledWith("openai");
  expect(screen.getByText("Connect Anthropic")).toBeTruthy();
  expect(screen.queryByText("Connect Voices")).toBeNull(); // not a chat AI
});

it("with AI connected but no model picked, opens the picker", () => {
  const onPickModel = vi.fn();
  render(<ModelSetupNotice state={{ kind: "pick", held: 1, why: "" }} onPickModel={onPickModel} />);
  expect(screen.getByRole("status").textContent).toContain("A message is waiting and runs once you pick a model.");
  fireEvent.click(screen.getByText("Pick a model"));
  expect(onPickModel).toHaveBeenCalled();
  fireEvent.click(screen.getByText("Set a default for new chats"));
  expect(nav.openDefaultModelSettings).toHaveBeenCalled();
});

it("with the chat's model on a service that isn't connected, offers Connect or another model", () => {
  const onPickModel = vi.fn();
  render(
    <ModelSetupNotice state={{ kind: "not_connected", provider: "openai", label: "OpenAI" }} onPickModel={onPickModel} />,
  );
  fireEvent.click(screen.getByText("Connect OpenAI"));
  expect(nav.openLlmsProviderSettings).toHaveBeenCalledWith("openai");
  fireEvent.click(screen.getByText("Pick another model"));
  expect(onPickModel).toHaveBeenCalled();
});
