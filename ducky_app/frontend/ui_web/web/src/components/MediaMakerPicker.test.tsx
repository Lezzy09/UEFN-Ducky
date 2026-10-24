// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AutomationNodeDto } from "../types/panel";

const api = vi.hoisted(() => ({ list_workflow_nodes: vi.fn(), get_settings: vi.fn(), save_agent_settings: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));

const { MediaMakerPicker, makersFrom } = await import("./MediaMakerPicker");

const backend = (id: string, plugin: string, plugin_id: string, available: boolean) =>
  ({ id, label: id, plugin, plugin_id, credits: 5, cost: "~5 credits", available, ...(available ? {} : { reason: `Install the ${plugin} plugin from the Store.` }) });
const NODES = [
  { type: "image.generate", backends: [backend("ducky_ai_image", "Ducky AI", "account", true), backend("openai_image", "OpenAI", "openai", false)] },
  { type: "mesh.generate", backends: [backend("meshy_text_to_3d", "Meshy", "meshy", false), backend("tripo", "3D AI Studio", "studio3d", true)] },
  { type: "mesh.from_image", backends: [backend("meshy_image_to_3d", "Meshy", "meshy", true)] },
] as unknown as AutomationNodeDto[];

afterEach(cleanup);

it("lists one maker per plugin, ready when any of its backends can run", () => {
  expect(makersFrom(NODES, "image").map((m) => [m.id, m.ready])).toEqual([["account", true], ["openai", false]]);
  expect(makersFrom(NODES, "mesh").map((m) => [m.id, m.ready])).toEqual([["meshy", true], ["studio3d", true]]);
});

it("saves the pick where Settings keeps it and says what one not set up needs", async () => {
  api.list_workflow_nodes.mockResolvedValue({ nodes: NODES });
  api.get_settings.mockResolvedValue({ default_image_provider: "" });
  render(<MediaMakerPicker kind="image" label="Pictures" />);
  fireEvent.click(await screen.findByRole("button", { name: "Pictures" }));
  fireEvent.click(await screen.findByRole("radio", { name: /OpenAI/ }));
  expect(api.save_agent_settings).toHaveBeenCalledWith({ default_image_provider: "openai" });
  await waitFor(() => expect(screen.getByText("Install the OpenAI plugin from the Store.")).toBeTruthy());
});
