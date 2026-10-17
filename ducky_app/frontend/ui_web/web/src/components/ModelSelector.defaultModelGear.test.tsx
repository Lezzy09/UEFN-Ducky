// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => new Proxy({} as Record<string, unknown>, {
  get: (_t, key) => {
    if (key === "then") return undefined;
    if (key === "get_models_catalog") {
      return async () => ({ models: [{ id: "ducky-brain", name: "Ducky AI", provider: "uefn_ducky", provider_key: "uefn_ducky" }] });
    }
    return async () => (/^(list|load)_/.test(String(key)) ? [] : {});
  },
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false, requireApi: () => api }));
vi.mock("../hooks/usePluginContributions", () => ({
  usePluginContributions: () => ({
    llm_providers: [{ id: "uefn_ducky", label: "Ducky AI", plugin_id: "account" }],
    llm_coding_agents: [],
  }),
}));
const settings = vi.hoisted(() => ({ openDefaultModelSettings: vi.fn() }));
vi.mock("../navigation/openSettingsTab", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../navigation/openSettingsTab")>()),
  openDefaultModelSettings: settings.openDefaultModelSettings,
}));

import { ModelSelector } from "./ModelSelector";
import { loadModelsCatalog } from "../hooks/modelsCatalogCache";

beforeEach(async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  await loadModelsCatalog({ force: true });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("the composer's model picker has a gear that opens the Default Model setting", async () => {
  const { container } = render(
    <ModelSelector selectedModel="ducky-brain" setSelectedModel={() => undefined}
                   codingAgent="ducky" setCodingAgent={() => undefined} preserveSelection />,
  );
  await act(async () => {});
  fireEvent.click(container.querySelector(".model-selector-btn")!);
  await act(async () => {});
  // It opens on the picked model's gateway, whose gear is that gateway's settings.
  expect(screen.getByRole("button", { name: "Open Ducky AI settings" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to gateways" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open Default Model settings" }));
  expect(settings.openDefaultModelSettings).toHaveBeenCalledTimes(1);
});
