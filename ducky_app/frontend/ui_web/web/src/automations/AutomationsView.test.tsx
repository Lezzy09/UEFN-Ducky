// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AutomationsView } from "./AutomationsView";
import type { AutomationDto } from "../types/panel";

const api = vi.hoisted(() => ({ list_pipelines: vi.fn(), list_pipeline_nodes: vi.fn(), get_pipeline: vi.fn(), save_pipeline: vi.fn(), list_recent_projects: vi.fn(), set_project_root: vi.fn(), list_agent_profiles: vi.fn(), list_all_conversations: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("./AutomationTemplatePicker", () => ({ AutomationTemplatePicker: () => null }));

let saved: AutomationDto;
beforeEach(() => {
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1; this.pointerType = init.pointerType || "mouse"; }
  }
  vi.stubGlobal("PointerEvent", TestPointerEvent);
  HTMLElement.prototype.setPointerCapture = vi.fn();
  document.elementsFromPoint = vi.fn(() => []);
  saved = { id: "p", name: "Example", enabled: true, kind: "pipeline", graph: {
    nodes: [
      { id: "s", type: "start.chat", label: "Chat", x: 0, y: 0, config: {} },
      { id: "a", type: "flow.wait", label: "Pause", description: "Pause description", x: 280, y: 0, config: {} },
      { id: "b", type: "flow.wait", label: "Continue", x: 560, y: 0, config: {} },
    ], edges: [{ source: "s", target: "a", kind: "main" }],
  } };
  api.list_pipelines.mockResolvedValue({ pipelines: [{ id: "p", name: "Example", enabled: true }] });
  api.list_pipeline_nodes.mockResolvedValue({ nodes: [{ type: "start.chat", label: "Chat", role: "starter", group: "Starting" }, { type: "flow.wait", label: "Wait", group: "Logic", config_fields: [{ id: "seconds", label: "Seconds", type: "number" }] }] });
  api.get_pipeline.mockImplementation(async () => ({ pipeline: structuredClone(saved) }));
  api.list_agent_profiles.mockResolvedValue({ profiles: [{ id: "artist", name: "My Artist", ducky_style: "artist" }], template_profiles: [{ id: "artist", name: "Original Artist" }, { id: "coder", name: "Verse Coder", ducky_style: "hacker" }], blank_profile_id: "__blank__" });
  api.list_all_conversations.mockResolvedValue([{ id: "existing", title: "Build my island", ducky_name: "Level Designer", project_name: "Island Two" }, { id: "hub", title: "Group hub", is_group: true }]);
  api.list_recent_projects.mockResolvedValue([
    { path: "C:/Projects/FirstIsland", name: "First Island", slug: "first", active: true },
    { path: "C:/Projects/SecondIsland", name: "Second Island", slug: "second", active: false },
  ]);
  api.save_pipeline.mockImplementation(async (doc: AutomationDto) => { saved = structuredClone(doc); return { pipeline: saved }; });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

async function open() {
  const view = render(<AutomationsView kind="pipeline" />);
  fireEvent.click(await screen.findByText("Example"));
  await screen.findByRole("button", { name: "Connect from Pause" });
  return view;
}
async function save() { fireEvent.click(screen.getByText("Save", { selector: "button" })); await waitFor(() => expect(api.save_pipeline).toHaveBeenCalled()); }
function wire(from: string, to: string, cancel = false) {
  const source = screen.getByRole("button", { name: from });
  const target = screen.getByRole("button", { name: to });
  vi.mocked(document.elementsFromPoint).mockReturnValue([target]);
  fireEvent.pointerDown(source, { button: 0, pointerId: 1 });
  if (cancel) fireEvent.pointerCancel(source, { pointerId: 1 });
  else fireEvent.pointerUp(source, { pointerId: 1, clientX: 600, clientY: 80 });
}

describe("pipeline editor interactions", () => {
  async function openAgentNode(config: Record<string, unknown> = {}) {
    saved.graph.nodes[1].type = "pipeline.agent";
    saved.graph.nodes[1].config = config;
    api.list_pipeline_nodes.mockResolvedValue({ nodes: [
      { type: "start.chat", label: "Chat", role: "starter", group: "Starting" },
      { type: "pipeline.agent", label: "Agent", group: "Agents", config_fields: [{ id: "ducky", label: "Assign ducky", type: "ducky" }] },
    ] });
    await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
  }
  it("lists existing duckies across projects, saved profiles and templates without duplicates", async () => {
    await openAgentNode();
    await screen.findByRole("option", { name: "My Artist" });
    expect(screen.getByRole("option", { name: "Verse Coder" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Level Designer — Build my island (Island Two)" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Original Artist" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Group hub" })).toBeNull();
    expect(screen.getByText("Node appearance").closest("details")?.open).toBe(false);
    expect(api.list_all_conversations).toHaveBeenCalledWith(true);
    fireEvent.change(screen.getByLabelText("Assign ducky"), { target: { value: "chat:existing" } });
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("chat:existing");
    fireEvent.click(screen.getByText("Example"));
    await waitFor(() => expect(screen.queryByLabelText("Assign ducky")).toBeNull());
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
    await screen.findByRole("option", { name: "My Artist" });
    expect((screen.getByLabelText("Assign ducky") as HTMLSelectElement).value).toBe("chat:existing");
  });
  it("saves create-at-run-time explicitly so it overrides an older profile assignment", async () => {
    await openAgentNode({ profile_id: "artist", prompt: "Build", model: "saved-model" });
    await screen.findByRole("option", { name: "My Artist" });
    expect((screen.getByLabelText("Assign ducky") as HTMLSelectElement).value).toBe("artist");
    fireEvent.change(screen.getByLabelText("Assign ducky"), { target: { value: "__new__" } });
    await save();
    expect(saved.graph.nodes[1].config).toEqual({ profile_id: "artist", prompt: "Build", model: "saved-model", ducky: "__new__" });
  });
  it("shows legacy profile names as a named selection and saves template choices", async () => {
    await openAgentNode({ ducky: "My Artist" });
    await screen.findByRole("option", { name: "My Artist" });
    expect((screen.getByLabelText("Assign ducky") as HTMLSelectElement).value).toBe("artist");
    fireEvent.change(screen.getByLabelText("Assign ducky"), { target: { value: "coder" } });
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("coder");
  });
  it("preserves unavailable assignments and still lists profiles when chat loading fails", async () => {
    api.list_all_conversations.mockRejectedValue(new Error("offline"));
    await openAgentNode({ ducky: "chat:missing" });
    await screen.findByRole("option", { name: "Some duckies could not be loaded — reopen to retry" });
    expect(screen.getByRole("option", { name: "My Artist" })).toBeTruthy();
    expect((screen.getByLabelText("Assign ducky") as HTMLSelectElement).value).toBe("chat:missing");
    api.list_all_conversations.mockResolvedValue([{ id: "existing", title: "Build my island", ducky_name: "Level Designer", project_name: "Island Two" }]);
    fireEvent.focus(screen.getByLabelText("Assign ducky"));
    await screen.findByRole("option", { name: "Level Designer — Build my island (Island Two)" });
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("chat:missing");
  });
  it("defaults to creating a ducky at run time even with an empty library", async () => {
    api.list_agent_profiles.mockResolvedValue({ profiles: [], template_profiles: [], blank_profile_id: "__blank__" });
    api.list_all_conversations.mockResolvedValue([]);
    await openAgentNode();
    await waitFor(() => expect(screen.queryByRole("option", { name: "Loading duckies…" })).toBeNull());
    expect((screen.getByLabelText("Assign ducky") as HTMLSelectElement).value).toBe("__new__");
  });
  async function openProjectNode(project = "") {
    saved.graph.nodes[1].type = "uefn.open_project";
    saved.graph.nodes[1].config = { project, timeout: 180 };
    api.list_pipeline_nodes.mockResolvedValue({ nodes: [
      { type: "start.chat", label: "Chat", role: "starter", group: "Starting" },
      { type: "uefn.open_project", label: "Open UEFN project", group: "UEFN", config_fields: [{ id: "project", label: "UEFN project", type: "project" }] },
    ] });
    await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
  }
  it("selects a saved UEFN project, preserves it on reload, and does not switch the active project while editing", async () => {
    await openProjectNode();
    await screen.findByRole("option", { name: "Second Island" });
    expect((screen.getByLabelText("UEFN project") as HTMLSelectElement).value).toBe("");
    fireEvent.change(screen.getByLabelText("UEFN project"), { target: { value: "C:/Projects/SecondIsland" } });
    await save();
    expect(saved.graph.nodes[1].config).toEqual({ project: "C:/Projects/SecondIsland", timeout: 180 });
    expect(api.set_project_root).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Example"));
    await waitFor(() => expect(screen.queryByLabelText("UEFN project")).toBeNull());
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
    await screen.findByRole("option", { name: "Second Island" });
    expect((screen.getByLabelText("UEFN project") as HTMLSelectElement).value).toBe("C:/Projects/SecondIsland");
  });
  it("preserves a previously typed project path when it is absent from saved projects", async () => {
    await openProjectNode("D:/Existing/Island.uefnproject");
    await screen.findByRole("option", { name: "Second Island" });
    expect((screen.getByLabelText("UEFN project") as HTMLSelectElement).value).toBe("D:/Existing/Island.uefnproject");
    await save();
    expect(saved.graph.nodes[1].config.project).toBe("D:/Existing/Island.uefnproject");
  });
  it("keeps the saved target on list errors and retries when the dropdown is reopened", async () => {
    api.list_recent_projects.mockRejectedValueOnce(new Error("offline"));
    await openProjectNode("C:/Projects/SecondIsland");
    await screen.findByRole("option", { name: "Could not load projects — reopen to retry" });
    expect((screen.getByLabelText("UEFN project") as HTMLSelectElement).value).toBe("C:/Projects/SecondIsland");
    fireEvent.focus(screen.getByLabelText("UEFN project"));
    await screen.findByRole("option", { name: "Second Island" });
  });
  it("explains an empty project list and retains the current-project default", async () => {
    api.list_recent_projects.mockResolvedValue([]);
    await openProjectNode();
    await screen.findByRole("option", { name: "No saved projects — add one in Ducky’s project menu" });
    expect((screen.getByLabelText("UEFN project") as HTMLSelectElement).value).toBe("");
  });
  it("connects output to input, prevents duplicates, and saves the graph", async () => {
    await open();
    wire("Connect from Pause", "Connect to Continue");
    wire("Connect from Pause", "Connect to Continue");
    await save();
    expect(saved.graph.edges).toHaveLength(2);
    expect(saved.graph.edges[1]).toEqual({ source: "a", target: "b", kind: "main" });
  });
  it("supports reverse dragging from input to output", async () => {
    await open();
    wire("Connect to Continue", "Connect from Pause");
    await save();
    expect(saved.graph.edges[1]).toEqual({ source: "a", target: "b", kind: "main" });
  });
  it("rejects same-direction connections and cancels interrupted drags", async () => {
    await open();
    wire("Connect from Pause", "Connect from Continue");
    wire("Connect from Pause", "Connect to Continue", true);
    await save();
    expect(saved.graph.edges).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Connect to Chat input" })).toBeNull();
  });
  it("resizes an expanded node in graph coordinates and saves its width", async () => {
    const { container } = await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
    const handle = screen.getByRole("button", { name: "Resize node" });
    fireEvent.pointerDown(handle, { button: 0, clientX: 500 });
    fireEvent.pointerMove(container.querySelector(".aw-board")!, { clientX: 620 });
    fireEvent.pointerUp(handle, { clientX: 620 });
    await save();
    expect(saved.graph.nodes[1].width).toBe(440);
    expect(screen.queryByText("Wires")).toBeNull();
  });
  it("hides details at overview zoom, restores them, and collapses from the menu", async () => {
    const { container } = await open();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit node" })[1]);
    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.queryByRole("button", { name: "Collapse node" })).toBeNull();
    expect(screen.queryByText("Pause description")).toBeNull();
    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("button", { name: "Collapse node" })).toBeTruthy();
    fireEvent.contextMenu(container.querySelector(".aw-board")!, { clientX: 200, clientY: 200 });
    fireEvent.click(screen.getByText("Collapse all nodes"));
    expect(screen.queryByRole("button", { name: "Collapse node" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Add node" })).toBeTruthy();
  });
  it("selects a connection without deleting it and edits its branch route", async () => {
    const { container } = await open();
    fireEvent.click(container.querySelector(".aw-wire")!);
    fireEvent.change(screen.getByLabelText("Connection route"), { target: { value: "false" } });
    await save();
    expect(saved.graph.edges).toEqual([{ source: "s", target: "a", kind: "false" }]);
    api.save_pipeline.mockClear();
    fireEvent.click(screen.getByText("Disconnect"));
    await save();
    expect(saved.graph.edges).toEqual([]);
  });
  it.each([0, 1, 2])("pans empty canvas with mouse button %s", async (button) => {
    const { container } = await open();
    const board = container.querySelector(".aw-board")!;
    fireEvent.pointerDown(board, { button, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(board, { clientX: 180, clientY: 150 });
    fireEvent.pointerUp(board, { button, clientX: 180, clientY: 150 });
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toBe("translate(120px, 90px) scale(1)");
    if (button === 2) {
      fireEvent.contextMenu(board, { clientX: 180, clientY: 150 });
      expect(screen.queryByRole("dialog", { name: "Add node" })).toBeNull();
    }
  });
  it("supports touch panning, pinch zoom and cancellation", async () => {
    const { container } = await open();
    const board = container.querySelector(".aw-board")!;
    const touch = { pointerType: "touch", button: 0 };
    fireEvent.pointerDown(board, { ...touch, pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(board, { ...touch, pointerId: 1, clientX: 120, clientY: 140 });
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toBe("translate(60px, 80px) scale(1)");
    fireEvent.pointerDown(board, { ...touch, pointerId: 2, clientX: 220, clientY: 140 });
    fireEvent.pointerMove(board, { ...touch, pointerId: 2, clientX: 320, clientY: 140 });
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toContain("scale(2)");
    fireEvent.pointerCancel(board, { ...touch, pointerId: 2 });
    const stopped = (container.querySelector(".aw-world") as HTMLElement).style.transform;
    fireEvent.pointerMove(board, { ...touch, pointerId: 1, clientX: 600, clientY: 600 });
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toBe(stopped);
    expect(saved.graph.edges).toHaveLength(1);
  });
  it("opens the node menu with a touch-friendly button and preserves regular right-click", async () => {
    const { container } = await open();
    fireEvent.click(screen.getByRole("button", { name: "+ Nodes" }));
    expect(screen.getByRole("dialog", { name: "Add node" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    const board = container.querySelector(".aw-board")!;
    fireEvent.pointerDown(board, { button: 2, clientX: 180, clientY: 150 });
    fireEvent.pointerUp(board, { button: 2, clientX: 180, clientY: 150 });
    fireEvent.contextMenu(board, { clientX: 180, clientY: 150 });
    expect(screen.getByRole("dialog", { name: "Add node" })).toBeTruthy();
  });
  it("uses distinct start/end roles, renames old Finish nodes and hides end outputs", async () => {
    saved.graph.nodes[2].type = "pipeline.finish";
    saved.graph.nodes[2].label = "Finish";
    const { container } = await open();
    expect(screen.getByText("Chat input")).toBeTruthy();
    expect(screen.getByText("Return to user")).toBeTruthy();
    expect(container.querySelector('[data-aw-node="s"]')?.classList.contains("aw-node--starter")).toBe(true);
    expect(container.querySelector('[data-aw-node="b"]')?.classList.contains("aw-node--end")).toBe(true);
    expect(screen.queryByRole("button", { name: "Connect from Return to user" })).toBeNull();
    wire("Connect to Pause", "Connect to Return to user");
    await save();
    expect(saved.graph.edges).toHaveLength(1);
  });
  it("shows the assigned ducky's real artwork", async () => {
    await openAgentNode({ ducky: "artist" });
    await waitFor(() => expect(document.querySelector('[data-aw-node="a"] .aw-node-icon img')?.getAttribute("src")).toContain("Artist.png"));
  });
});
