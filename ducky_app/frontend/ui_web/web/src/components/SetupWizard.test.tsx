// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StarterPluginDto } from "../types/panel";

const fake = vi.hoisted(() => {
  const api = {
    duckyos_store_catalog: vi.fn(),
    get_key_status: vi.fn(),
    list_coding_agents: vi.fn(),
    save_agent_settings: vi.fn(),
    coding_agent_login: vi.fn(),
    coding_agent_login_status: vi.fn(),
    coding_agent_login_submit: vi.fn(),
    coding_agent_login_cancel: vi.fn(),
    detect_coding_agent_cli: vi.fn(),
  };
  return { api, runBridgeJob: vi.fn(), providers: [] as unknown[] };
});

vi.mock("../hooks/usePanelApi", () => ({ getApi: () => fake.api }));
vi.mock("../hooks/bridgeJobAsync", () => ({ runBridgeJob: fake.runBridgeJob }));
vi.mock("../hooks/usePanelPushBus", () => ({ installPanelPushBus: () => {}, subscribePanelPush: () => () => {} }));
vi.mock("../hooks/storeCatalogCache", () => ({ peekStoreCatalogCache: () => null, rememberStoreCatalog: () => {} }));
vi.mock("../hooks/usePluginContributions", () => ({
  usePluginContributions: () => ({ llm_providers: fake.providers, llm_coding_agents: [], ready: true }),
}));
vi.mock("../hooks/modelsCatalogCache", () => ({ refreshModelsCatalog: vi.fn(), rereadModelsCatalog: vi.fn() }));

const { SetupWizard } = await import("./SetupWizard");

const PLUGINS: StarterPluginDto[] = [
  { slug: "openai", label: "OpenAI", group: "gateway", installed: false },
  { slug: "verse", label: "Verse", group: "editor", installed: true },
];

const OPENAI = {
  id: "openai",
  label: "OpenAI",
  kind: "secret" as const,
  secret_key: "openai",
  plugin_id: "openai",
  order: 20,
};
const ANTHROPIC = { ...OPENAI, id: "anthropic", label: "Anthropic", secret_key: "anthropic", plugin_id: "anthropic", order: 10 };
const CURSOR = { id: "cursor", label: "Cursor", kind: "url" as const, plugin_id: "cursor", order: 30 };

const AGENTS = [
  { id: "codex", label: "Codex", plugin_id: "openai", available: true, logged_in: true, enabled: true, status: "ok" },
  {
    id: "claude_code",
    label: "Claude Code",
    plugin_id: "anthropic",
    available: true,
    logged_in: false,
    can_login: true,
    enabled: true,
    status: "Not logged in",
  },
  {
    id: "cursor",
    label: "Cursor Agent",
    plugin_id: "cursor",
    available: false,
    logged_in: null,
    enabled: true,
    status: "CLI not found",
    install_help: "Install the Cursor CLI, then press Check.",
  },
  { id: "ducky", label: "Ducky", plugin_id: "", available: true, enabled: true, status: "ok" },
];

function wizard(over: Partial<Parameters<typeof SetupWizard>[0]> = {}) {
  const props = {
    step: "welcome" as const,
    onStep: vi.fn(),
    plugins: PLUGINS,
    rows: { openai: { phase: "ready" as const }, verse: { phase: "installed" as const } },
    installing: false,
    installError: "",
    onInstall: vi.fn(),
    onClose: vi.fn(),
    onShowMe: vi.fn(),
    ...over,
  };
  render(<SetupWizard {...props} />);
  return props;
}

beforeEach(() => {
  fake.providers = [];
  fake.api.duckyos_store_catalog.mockResolvedValue({
    ok: true,
    items: [{ slug: "openai", name: "OpenAI", description: "GPT models for chats. Also Codex.", icon_data_url: "data:image/png;base64,AA" }],
  });
  fake.api.get_key_status.mockResolvedValue({});
  fake.api.list_coding_agents.mockResolvedValue({ agents: [] });
  fake.api.save_agent_settings.mockResolvedValue(undefined);
  fake.api.coding_agent_login_status.mockResolvedValue({ ok: true, logged_in: false });
  fake.api.coding_agent_login_cancel.mockResolvedValue({ ok: true });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SetupWizard", () => {
  it("welcomes with the logo and the three steps", () => {
    const props = wizard();
    expect(screen.getByRole("dialog", { name: "Welcome to UEFN Ducky" })).toBeTruthy();
    expect(document.querySelector("img.setup-wizard-logo")?.getAttribute("src")).toBe("./OnlineMCPIcon.png");
    expect(screen.getByRole("list", { name: "Setup steps" }).textContent).toContain("Connect AI");
    fireEvent.click(screen.getByRole("button", { name: /Get started/ }));
    expect(props.onStep).toHaveBeenCalledWith("plugins");
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(props.onClose).toHaveBeenCalledWith("skip");
  });

  it("lists the plugins by group with their Store icon, line and status", async () => {
    const props = wizard({ step: "plugins" });
    expect(screen.getByRole("region", { name: "AI gateways" }).textContent).toContain("OpenAI");
    expect(screen.getByRole("region", { name: "UEFN editor tools" }).textContent).toContain("Verse");
    await waitFor(() => expect(screen.getByText("GPT models for chats.")).toBeTruthy());
    expect(document.querySelector(".setup-wizard-plugin.is-ready img")?.getAttribute("src")).toBe("data:image/png;base64,AA");
    expect(screen.getByText("1 of 2 installed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Install 1 plugin$/ }));
    expect(props.onInstall).toHaveBeenCalled();
  });

  it("lists Pipe voices in its own Voices group", () => {
    wizard({ step: "plugins", plugins: [...PLUGINS, { slug: "piper", label: "Pipe voices", group: "voice", installed: false }] });
    expect(screen.getByRole("region", { name: "UEFN editor tools" }).textContent).not.toContain("Pipe");
    expect(screen.getByRole("region", { name: "Voices" }).textContent).toContain("Pipe voices");
  });

  it("shows installing and failed rows, and Try again after a failure", () => {
    wizard({ step: "plugins", installing: true, rows: { openai: { phase: "installing" }, verse: { phase: "installed" } } });
    expect(screen.getByRole("button", { name: /Installing 2 of 2/ })).toHaveProperty("disabled", true);
    expect(document.querySelector(".setup-wizard-plugin.is-installing")?.textContent).toContain("Installing");
    cleanup();
    wizard({ step: "plugins", rows: { openai: { phase: "error", detail: "Store is offline" }, verse: { phase: "installed" } } });
    expect(screen.getByText("Store is offline")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Try again/ })).toBeTruthy();
  });

  it("goes on to the AI step once everything is installed", () => {
    const props = wizard({ step: "plugins", rows: { openai: { phase: "installed" }, verse: { phase: "installed" } } });
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(props.onStep).toHaveBeenCalledWith("ai");
  });

  it("explains both ways to connect and saves a key that tests ok", async () => {
    fake.providers = [OPENAI];
    fake.runBridgeJob.mockResolvedValue({ ok: true, detail: "ok" });
    const props = wizard({ step: "ai" });
    const ways = document.querySelector<HTMLElement>(".setup-wizard-ways")!;
    expect(within(ways).getByText("API key")).toBeTruthy();
    expect(within(ways).getByText("Coding agent")).toBeTruthy();
    expect(screen.getByText("Not connected")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("OpenAI API key"), { target: { value: " sk-test " } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Test & save" }));
    });
    expect(fake.runBridgeJob).toHaveBeenCalledWith("test_key", ["openai", "sk-test"], 300_000);
    expect(fake.api.save_agent_settings).toHaveBeenCalledWith({ keys: { openai: "sk-test" } });
    expect(screen.getByText("Key saved. Duckies can use it now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show me how" }));
    expect(props.onShowMe).toHaveBeenCalledWith(OPENAI);
    fireEvent.click(screen.getByRole("button", { name: /Finish/ }));
    expect(props.onClose).toHaveBeenCalledWith("finish");
  });

  it("keeps a key that fails the test out of settings", async () => {
    fake.providers = [OPENAI];
    fake.runBridgeJob.mockResolvedValue({ ok: false, detail: "Incorrect API key" });
    wizard({ step: "ai" });
    fireEvent.change(screen.getByLabelText("OpenAI API key"), { target: { value: "bad" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Test & save" }));
    });
    expect(screen.getByText("Incorrect API key")).toBeTruthy();
    expect(fake.api.save_agent_settings).not.toHaveBeenCalled();
  });

  it("shows a provider connected through its signed-in coding agent", async () => {
    fake.providers = [OPENAI];
    fake.api.list_coding_agents.mockResolvedValue({
      agents: [{ id: "codex", label: "Codex", plugin_id: "openai", available: true, logged_in: true, enabled: true, status: "ok" }],
    });
    wizard({ step: "ai" });
    await waitFor(() => expect(screen.getByLabelText("Codex: Logged in")).toBeTruthy());
    expect(screen.getByLabelText("OpenAI: Connected")).toBeTruthy();
    expect(screen.getByLabelText("OpenAI API key: No key")).toBeTruthy();
  });

  it("shows each provider's key and each coding agent's login, connected or not", async () => {
    fake.providers = [OPENAI, ANTHROPIC, CURSOR];
    fake.api.get_key_status.mockResolvedValue({ openai: true });
    fake.api.list_coding_agents.mockResolvedValue({ agents: AGENTS });
    wizard({ step: "ai" });
    await waitFor(() => expect(screen.getByLabelText("Claude Code: Not logged in")).toBeTruthy());
    expect(screen.getByLabelText("OpenAI: Connected")).toBeTruthy();
    expect(screen.getByLabelText("OpenAI API key: Key saved")).toBeTruthy();
    expect(screen.getByLabelText("Codex: Logged in")).toBeTruthy();
    expect(screen.getByLabelText("Anthropic: Not connected")).toBeTruthy();
    expect(screen.getByLabelText("Anthropic API key: No key")).toBeTruthy();
    expect(screen.getByLabelText("Cursor: Not connected")).toBeTruthy();
    expect(screen.getByLabelText("Cursor Agent: Not installed")).toBeTruthy();
    expect(screen.getByText("Install the Cursor CLI, then press Check.")).toBeTruthy();
    expect(screen.queryByLabelText(/Ducky:/)).toBeNull(); // Ducky's own agent is not a login
    // Log in only where the gateway can run it; a key field only for API-key providers.
    const claude = screen.getByRole("list", { name: "Anthropic coding agents" });
    expect(within(claude).getByRole("button", { name: "Log in" })).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "OpenAI coding agents" })).queryByRole("button", { name: "Log in" })).toBeNull();
    expect(screen.queryByLabelText("Cursor API key")).toBeNull();
  });

  it("logs a coding agent in the way Settings does, then shows it logged in", async () => {
    fake.providers = [ANTHROPIC];
    let loggedIn = false;
    fake.api.list_coding_agents.mockImplementation(() =>
      Promise.resolve({ agents: [{ ...AGENTS[1]!, logged_in: loggedIn }] }),
    );
    fake.api.coding_agent_login.mockResolvedValue({ ok: true, auth_url: "https://claude.ai/oauth?x=1" });
    fake.api.coding_agent_login_submit.mockImplementation(() => {
      loggedIn = true;
      return Promise.resolve({ ok: true, logged_in: true });
    });
    wizard({ step: "ai" });
    fireEvent.click(await screen.findByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Log in to Claude Code")).toBeTruthy();
    await waitFor(() => expect(fake.api.coding_agent_login).toHaveBeenCalledWith("claude_code"));
    fireEvent.change(await screen.findByPlaceholderText("Paste the login code"), { target: { value: "abc#123" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    });
    expect(fake.api.coding_agent_login_submit).toHaveBeenCalledWith("claude_code", "abc#123");
    await waitFor(() => expect(screen.getByLabelText("Claude Code: Logged in")).toBeTruthy());
    expect(screen.getByLabelText("Anthropic: Connected")).toBeTruthy();
    expect(screen.queryByText("Log in to Claude Code")).toBeNull();
  });

  it("checks an agent again after it was installed or signed in elsewhere", async () => {
    fake.providers = [CURSOR];
    let installed = false;
    fake.api.list_coding_agents.mockImplementation(() =>
      Promise.resolve({ agents: [{ ...AGENTS[2]!, available: installed, logged_in: installed ? true : null }] }),
    );
    fake.api.detect_coding_agent_cli.mockImplementation(() => {
      installed = true;
      return Promise.resolve({ ok: true });
    });
    wizard({ step: "ai" });
    fireEvent.click(await screen.findByRole("button", { name: "Check" }));
    await waitFor(() => expect(screen.getByLabelText("Cursor Agent: Logged in")).toBeTruthy());
    expect(fake.api.detect_coding_agent_cli).toHaveBeenCalledWith("cursor");
    expect(screen.getByLabelText("Cursor: Connected")).toBeTruthy();
  });

  it("sends people back to install when no gateway is there", () => {
    const props = wizard({ step: "ai" });
    fireEvent.click(screen.getByRole("button", { name: "Go back and install the plugins" }));
    expect(props.onStep).toHaveBeenCalledWith("plugins");
  });
});
