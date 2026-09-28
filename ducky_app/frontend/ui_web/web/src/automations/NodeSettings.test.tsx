// @vitest-environment jsdom
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NodeSettings } from "./NodeSettings";
import type { AutomationGraphNodeDto, AutomationNodeDto } from "../types/panel";

const api = vi.hoisted(() => ({ get_mcp_tools_catalog: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
let current: AutomationGraphNodeDto;
function Editor({ config, meta }: { config: Record<string, unknown>; meta?: AutomationNodeDto }) {
  const [node, setNode] = useState<AutomationGraphNodeDto>({ id: "tool", type: meta?.type || "tool.call", x: 0, y: 0, config });
  current = node;
  return <NodeSettings node={node} meta={meta} onChange={setNode} />;
}
beforeEach(() => {
  api.get_mcp_tools_catalog.mockResolvedValue({ tools: [
    { name: "blender_scene_info", description: "Inspect the scene", category_label: "Blender", parameters: [] },
    { name: "blender_add_object", description: "Add an object", category_label: "Blender", parameters: [
      { name: "object_name", type: "string", required: true, description: "Name in the scene" },
      { name: "size", type: "number", default: 1 },
      { name: "visible", type: "boolean", default: true },
    ] },
    { name: "meshy_generate", description: "Make a mesh", category_label: "Meshy", parameters: [] },
  ] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("node settings", () => {
  it("searches real tools, selects with radios and shows only relevant settings", async () => {
    render(<Editor config={{ name: "blender_scene_info", arguments_json: "{}" }} />);
    await screen.findByText("This tool needs no inputs.");
    expect(screen.queryByText("Arguments JSON")).toBeNull();
    expect(screen.queryByText("Label")).toBeNull();
    expect(screen.queryByText("Description")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Tool" }));
    expect(document.activeElement).toBe(screen.getByRole("searchbox", { name: "Search tools" }));
    fireEvent.change(document.activeElement!, { target: { value: "blender object" } });
    expect(screen.queryByRole("radio", { name: /meshy_generate/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /blender_add_object/ }));
    expect(current.config.name).toBe("blender_add_object");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "object name" }), { target: { value: "Island" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "size" }), { target: { value: "3.5" } });
    fireEvent.click(screen.getByRole("button", { name: "visible" }));
    fireEvent.click(screen.getByRole("radio", { name: "No", exact: true }));
    expect(current.config.arguments).toEqual({ object_name: "Island", size: 3.5, visible: false });
    expect(current.config.arguments_json).toBeUndefined();
  });
  it("keeps unknown arguments and templates when a known argument is edited", async () => {
    const args = { extra: { keep: true }, size: "${payload.size}", visible: "${payload.visible}" };
    render(<Editor config={{ name: "blender_add_object", arguments_json: JSON.stringify(args) }} />);
    fireEvent.change(await screen.findByRole("textbox", { name: "object name" }), { target: { value: "Rock" } });
    expect(current.config.arguments).toEqual({ ...args, object_name: "Rock" });
    expect(screen.queryByRole("spinbutton", { name: "size" })).toBeNull();
    expect(screen.queryByRole("button", { name: "visible" })).toBeNull();
    fireEvent.click(screen.getByText("Advanced inputs"));
    expect((screen.getByRole("textbox", { name: "Arguments JSON" }) as HTMLTextAreaElement).value).toContain("${payload.size}");
  });
  it("preserves invalid JSON for repair before allowing individual input changes", async () => {
    render(<Editor config={{ name: "blender_add_object", arguments_json: "{broken" }} />);
    await screen.findByRole("status");
    expect(screen.queryByRole("textbox", { name: "object name" })).toBeNull();
    expect((screen.getByRole("textbox", { name: "Arguments JSON" }) as HTMLTextAreaElement).value).toBe("{broken");
    fireEvent.change(screen.getByRole("textbox", { name: "Arguments JSON" }), { target: { value: '{"object_name":"Repaired"}' } });
    await waitFor(() => expect((screen.getByRole("textbox", { name: "object name" }) as HTMLInputElement).value).toBe("Repaired"));
  });
  it("retains a saved tool while its catalog is unavailable and retries on open", async () => {
    api.get_mcp_tools_catalog.mockRejectedValueOnce(new Error("offline"));
    render(<Editor config={{ name: "custom_tool", arguments: { value: 42 } }} />);
    await waitFor(() => expect(api.get_mcp_tools_catalog).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Tool" }));
    await screen.findByRole("radio", { name: /blender_scene_info/ });
    expect((screen.getByRole("radio", { name: /custom_tool/ }) as HTMLInputElement).checked).toBe(true);
    expect(current.config).toEqual({ name: "custom_tool", arguments: { value: 42 } });
  });
  it("uses a shared checkbox menu for multiple choices and retains saved unknown values", () => {
    render(<Editor config={{ targets: ["saved"] }} meta={{ type: "plugin.action", label: "Action", config_fields: [{ id: "targets", label: "Targets", type: "multiselect", options: [{ id: "one", label: "One" }, { id: "two", label: "Two" }] }] }} />);
    fireEvent.click(screen.getByRole("button", { name: "Targets" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "One" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Two" }));
    expect(current.config.targets).toEqual(["saved", "one", "two"]);
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("checkbox", { name: "Two" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Targets" }));
  });
});
