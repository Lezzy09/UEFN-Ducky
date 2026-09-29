// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AutomationsView } from "./AutomationsView";
import type { AutomationDto } from "../types/panel";

const api = vi.hoisted(() => ({ list_workflow_versions: vi.fn(), get_workflow_version: vi.fn(), list_automations: vi.fn(), list_automation_nodes: vi.fn(), get_automation: vi.fn(), save_automation: vi.fn(), run_automation: vi.fn(), delete_automation: vi.fn(), list_pipelines: vi.fn(), list_pipeline_nodes: vi.fn(), get_pipeline: vi.fn(), save_pipeline: vi.fn(), list_recent_projects: vi.fn(), set_project_root: vi.fn(), list_agent_profiles: vi.fn(), list_all_conversations: vi.fn(), get_mcp_tools_catalog: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api }));
vi.mock("./AutomationTemplatePicker", () => ({ AutomationTemplatePicker: ({ open, system, onSelect }: { open: boolean; system: string; onSelect: (template: null) => void }) => open ? <button onClick={() => onSelect(null)}>Create {system}</button> : null }));

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
  api.list_workflow_versions.mockResolvedValue({ ok: true, versions: [] });
  api.get_workflow_version.mockResolvedValue({ ok: false });
  api.get_mcp_tools_catalog.mockResolvedValue({ tools: [] });
  api.list_automations.mockResolvedValue({ automations: [{ id: "p", name: "Daily check", enabled: true }] });
  api.list_automation_nodes.mockResolvedValue({ nodes: [{ type: "start.cron", label: "Schedule", role: "starter", group: "Triggers" }] });
  api.get_automation.mockResolvedValue({ automation: { id: "p", name: "Daily check", enabled: true, kind: "automation", graph: { nodes: [{ id: "timer", type: "start.cron", x: 0, y: 0, config: {} }], edges: [] } } });
  api.save_automation.mockImplementation(async (doc: AutomationDto) => ({ automation: { ...structuredClone(doc), id: doc.id || "new-automation" } }));
  api.run_automation.mockResolvedValue({ ok: true, steps: [] });
  api.delete_automation.mockResolvedValue({ ok: true });
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
async function save() { fireEvent.click(screen.getByRole("button", { name: "Save", exact: true })); await waitFor(() => expect(api.save_pipeline).toHaveBeenCalled()); }
function editNode(id = "a") { fireEvent.click(document.querySelector(`[data-aw-node="${id}"] .aw-node-expand-toggle`)!); }
function dropdown(name: string) { fireEvent.click(screen.getByRole("button", { name, exact: true })); }
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
    editNode();
  }
  it("lists existing duckies across projects, saved profiles and templates without duplicates", async () => {
    await openAgentNode();
    dropdown("Assign ducky");
    await screen.findByRole("radio", { name: "My Artist" });
    expect(screen.getByRole("radio", { name: "Verse Coder" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Level Designer — Build my island (Island Two)" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Original Artist" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Group hub" })).toBeNull();
    expect(screen.queryByText("Node appearance")).toBeNull();
    expect(screen.queryByLabelText("Label")).toBeNull();
    expect(api.list_all_conversations).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("radio", { name: "Level Designer — Build my island (Island Two)" }));
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("chat:existing");
    fireEvent.click(screen.getByText("Example"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Assign ducky" })).toBeNull());
    editNode();
    dropdown("Assign ducky");
    await waitFor(() => expect((screen.getByRole("radio", { name: "Level Designer — Build my island (Island Two)" }) as HTMLInputElement).checked).toBe(true));
  });
  it("saves create-at-run-time explicitly so it overrides an older profile assignment", async () => {
    await openAgentNode({ profile_id: "artist", prompt: "Build", model: "saved-model" });
    dropdown("Assign ducky");
    await waitFor(() => expect((screen.getByRole("radio", { name: "My Artist" }) as HTMLInputElement).checked).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: "Create new when workflow runs" }));
    await save();
    expect(saved.graph.nodes[1].config).toEqual({ profile_id: "artist", prompt: "Build", model: "saved-model", ducky: "__new__" });
  });
  it("shows legacy profile names as a named selection and saves template choices", async () => {
    await openAgentNode({ ducky: "My Artist" });
    dropdown("Assign ducky");
    await waitFor(() => expect((screen.getByRole("radio", { name: "My Artist" }) as HTMLInputElement).checked).toBe(true));
    fireEvent.click(screen.getByRole("radio", { name: "Verse Coder" }));
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("coder");
  });
  it("preserves unavailable assignments and still lists profiles when chat loading fails", async () => {
    api.list_all_conversations.mockRejectedValue(new Error("offline"));
    await openAgentNode({ ducky: "chat:missing" });
    dropdown("Assign ducky");
    await screen.findByText("Some duckies could not be loaded — reopen to retry");
    expect(screen.getByRole("radio", { name: "My Artist" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: "Saved assignment — chat:missing" }) as HTMLInputElement).checked).toBe(true);
    api.list_all_conversations.mockResolvedValue([{ id: "existing", title: "Build my island", ducky_name: "Level Designer", project_name: "Island Two" }]);
    dropdown("Assign ducky");
    dropdown("Assign ducky");
    await screen.findByRole("radio", { name: "Level Designer — Build my island (Island Two)" });
    await save();
    expect(saved.graph.nodes[1].config.ducky).toBe("chat:missing");
  });
  it("defaults to creating a ducky at run time even with an empty library", async () => {
    api.list_agent_profiles.mockResolvedValue({ profiles: [], template_profiles: [], blank_profile_id: "__blank__" });
    api.list_all_conversations.mockResolvedValue([]);
    await openAgentNode();
    dropdown("Assign ducky");
    expect((screen.getByRole("radio", { name: "Create new when workflow runs" }) as HTMLInputElement).checked).toBe(true);
  });
  async function openProjectNode(project = "") {
    saved.graph.nodes[1].type = "uefn.open_project";
    saved.graph.nodes[1].config = { project, timeout: 180 };
    api.list_pipeline_nodes.mockResolvedValue({ nodes: [
      { type: "start.chat", label: "Chat", role: "starter", group: "Starting" },
      { type: "uefn.open_project", label: "Open UEFN project", group: "UEFN", config_fields: [{ id: "project", label: "UEFN project", type: "project" }] },
    ] });
    await open();
    editNode();
  }
  it("selects a saved UEFN project, preserves it on reload, and does not switch the active project while editing", async () => {
    await openProjectNode();
    dropdown("UEFN project");
    await screen.findByRole("radio", { name: /^Second Island/ });
    expect((screen.getByRole("radio", { name: "Current project (at run time)" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /^Second Island/ }));
    await save();
    expect(saved.graph.nodes[1].config).toEqual({ project: "C:/Projects/SecondIsland", timeout: 180 });
    expect(api.set_project_root).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Example"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "UEFN project" })).toBeNull());
    editNode();
    dropdown("UEFN project");
    await waitFor(() => expect((screen.getByRole("radio", { name: /^Second Island/ }) as HTMLInputElement).checked).toBe(true));
  });
  it("preserves a previously typed project path when it is absent from saved projects", async () => {
    await openProjectNode("D:/Existing/Island.uefnproject");
    dropdown("UEFN project");
    await screen.findByRole("radio", { name: /^Second Island/ });
    expect((screen.getByRole("radio", { name: "Saved project — D:/Existing/Island.uefnproject" }) as HTMLInputElement).checked).toBe(true);
    await save();
    expect(saved.graph.nodes[1].config.project).toBe("D:/Existing/Island.uefnproject");
  });
  it("keeps the saved target on list errors and retries when the dropdown is reopened", async () => {
    api.list_recent_projects.mockRejectedValue(new Error("offline"));
    await openProjectNode("C:/Projects/SecondIsland");
    dropdown("UEFN project");
    await screen.findByText("Could not load projects — reopen to retry");
    expect((screen.getByRole("radio", { name: "Saved project — C:/Projects/SecondIsland" }) as HTMLInputElement).checked).toBe(true);
    api.list_recent_projects.mockResolvedValue([{ path: "C:/Projects/SecondIsland", name: "Second Island" }]);
    dropdown("UEFN project");
    dropdown("UEFN project");
    await screen.findByRole("radio", { name: /^Second Island/ });
  });
  it("explains an empty project list and retains the current-project default", async () => {
    api.list_recent_projects.mockResolvedValue([]);
    await openProjectNode();
    dropdown("UEFN project");
    await screen.findByText("No saved projects — add one in Ducky’s project menu");
    expect((screen.getByRole("radio", { name: "Current project (at run time)" }) as HTMLInputElement).checked).toBe(true);
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
    editNode();
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
    editNode();
    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.queryByRole("button", { name: "Collapse node" })).toBeNull();
    expect(screen.queryByText("Pause description")).toBeNull();
    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("button", { name: "Collapse node" })).toBeTruthy();
    fireEvent.contextMenu(container.querySelector(".aw-board")!, { clientX: 200, clientY: 200 });
    fireEvent.click(screen.getByRole("button", { name: "Collapse all nodes", exact: true }));
    expect(screen.queryByRole("button", { name: "Collapse node" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Add node" })).toBeTruthy();
  });
  it("selects a connection without deleting it and edits its branch route", async () => {
    const { container } = await open();
    fireEvent.click(container.querySelector(".aw-wire")!);
    dropdown("Connection route");
    fireEvent.click(screen.getByRole("radio", { name: "False", exact: true }));
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
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toBe("translate(360px, 210px) scale(1)");
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
    expect((container.querySelector(".aw-world") as HTMLElement).style.transform).toBe("translate(300px, 200px) scale(1)");
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
    fireEvent.click(screen.getByRole("button", { name: "Add nodes" }));
    expect(screen.getByRole("dialog", { name: "Add node" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Filter nodes" }));
    fireEvent.keyDown(window, { key: "Escape" });
    const board = container.querySelector(".aw-board")!;
    fireEvent.pointerDown(board, { button: 2, clientX: 180, clientY: 150 });
    fireEvent.pointerUp(board, { button: 2, clientX: 180, clientY: 150 });
    fireEvent.contextMenu(board, { clientX: 180, clientY: 150 });
    const menu = screen.getByRole("dialog", { name: "Add node" });
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Filter nodes" }));
    fireEvent.change(document.activeElement!, { target: { value: "wait" } });
    expect(menu.querySelectorAll(".aw-tile")).toHaveLength(1);
    expect(menu.querySelector(".aw-tile")?.textContent).toContain("Wait");
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Filter nodes" }));
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
  it("reloads the canvas when chat saves the graph", async () => {
    render(<AutomationsView kind="pipeline" />);
    window.dispatchEvent(new CustomEvent("ducky:focus-graph", { detail: { kind: "pipeline", id: "p" } }));
    await waitFor(() => expect(api.get_pipeline).toHaveBeenCalledWith("p"));
    expect(await screen.findByDisplayValue("Example")).toBeTruthy();
  });
  it("clears the open graph when chat deletes it", async () => {
    await open();
    expect(screen.getByDisplayValue("Example")).toBeTruthy();
    window.dispatchEvent(new CustomEvent("ducky:graph-deleted", { detail: { kind: "pipeline", id: "p" } }));
    await waitFor(() => expect(screen.queryByDisplayValue("Example")).toBeNull());
  });
  it("shows the assigned ducky's real artwork", async () => {
    await openAgentNode({ ducky: "artist" });
    await waitFor(() => expect(document.querySelector('[data-aw-node="a"] .aw-node-icon img')?.getAttribute("src")).toContain("Artist.png"));
  });
});

describe("combined Workflows editor", () => {
  it("hides the workflow toolbar until a workflow is selected and after it is removed", async () => {
    render(<AutomationsView kind="pipeline" />);
    await screen.findByText("Example");
    expect(screen.queryByRole("toolbar", { name: "Workflow actions" })).toBeNull();
    fireEvent.click(screen.getByText("Daily check"));
    await screen.findByDisplayValue("Daily check");
    expect(screen.getByRole("toolbar", { name: "Workflow actions" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete", exact: true }));
    await waitFor(() => expect(screen.queryByRole("toolbar", { name: "Workflow actions" })).toBeNull());
  });
  it("collapses the entire list without losing the graph or individual section states", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Automations", exact: true }));
    const toggle = screen.getByRole("button", { name: "Workflows", exact: true });
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Pipelines", exact: true })).toBeNull();
    expect(screen.getByDisplayValue("Example")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect from Pause" })).toBeTruthy();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Pipelines", exact: true }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Automations", exact: true }).getAttribute("aria-expanded")).toBe("false");
  });
  it("collapses each section independently and switches catalogs without mixing matching IDs", async () => {
    await open();
    const pipelines = screen.getByRole("button", { name: "Pipelines", exact: true });
    fireEvent.click(pipelines);
    expect(screen.queryByRole("button", { name: "Exampleon" })).toBeNull();
    expect(screen.getByRole("button", { name: "Daily checkon" })).toBeTruthy();
    fireEvent.click(screen.getByText("Daily check"));
    await screen.findByDisplayValue("Daily check");
    expect(document.querySelectorAll('.aw-list-row.is-active')).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Add nodes" }));
    expect(await screen.findByRole("button", { name: "Schedule", exact: true })).toBeTruthy();
    expect(screen.queryByText("Wait")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(api.save_automation).toHaveBeenCalledWith(expect.objectContaining({ id: "p", kind: "automation" })));
    expect(api.save_pipeline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Test", exact: true }));
    await waitFor(() => expect(api.run_automation).toHaveBeenCalledWith("p"));
    fireEvent.click(screen.getByRole("button", { name: "Delete", exact: true }));
    await waitFor(() => expect(api.delete_automation).toHaveBeenCalledWith("p"));
    await waitFor(() => expect(screen.queryByDisplayValue("Daily check")).toBeNull());
  });
  it("uses the selected section's template type while another kind is on the board", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "New automation" }));
    fireEvent.click(screen.getByRole("button", { name: "Create automation" }));
    await waitFor(() => expect(api.save_automation).toHaveBeenCalledWith(expect.objectContaining({ id: "", kind: "automation" })));
    expect(api.save_pipeline).not.toHaveBeenCalled();
    await screen.findByDisplayValue("Untitled");
  });
  it("opens a chat-linked graph of either kind and expands its section", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Automations", exact: true }));
    await act(async () => { window.dispatchEvent(new CustomEvent("ducky:focus-graph", { detail: { kind: "automation", id: "p" } })); });
    await screen.findByDisplayValue("Daily check");
    expect(screen.getByRole("button", { name: "Automations", exact: true }).getAttribute("aria-expanded")).toBe("true");
    await act(async () => { window.dispatchEvent(new CustomEvent("ducky:graph-deleted", { detail: { kind: "pipeline", id: "p" } })); });
    expect(screen.getByDisplayValue("Daily check")).toBeTruthy();
  });
  it("keeps a delayed save from replacing the other section's newly selected graph", async () => {
    await open();
    let finish!: (value: { pipeline: AutomationDto }) => void;
    api.save_pipeline.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    fireEvent.click(screen.getByText("Daily check"));
    await screen.findByDisplayValue("Daily check");
    await act(async () => { finish({ pipeline: saved }); });
    expect(screen.getByDisplayValue("Daily check")).toBeTruthy();
  });
});

describe("inline node editing", () => {
  it("saves names on Enter and descriptions on blur without redundant settings", async () => {
    await open();
    const chat = document.querySelector('[data-aw-node="s"]')!;
    expect(chat.querySelector('.aw-node-expand-toggle')).toBeNull();
    fireEvent.doubleClick(chat.querySelector('.aw-node-body')!);
    expect(chat.querySelector('.aw-node-props')).toBeNull();
    fireEvent.click(chat.querySelector('[aria-label="Edit node name"]')!);
    const name = screen.getByRole("textbox", { name: "Node name" });
    expect(document.activeElement).toBe(name);
    fireEvent.change(name, { target: { value: "Image input" } });
    fireEvent.keyDown(name, { key: "Enter" });
    await waitFor(() => expect(saved.graph.nodes[0].label).toBe("Image input"));
    fireEvent.click(chat.querySelector('[aria-label="Edit node description"]')!);
    const description = screen.getByRole("textbox", { name: "Node description" });
    fireEvent.change(description, { target: { value: "Send your island concept" } });
    fireEvent.blur(description);
    await waitFor(() => expect(saved.graph.nodes[0].description).toBe("Send your island concept"));
    expect(screen.queryByLabelText("Label")).toBeNull();
  });
  it("cancels with Escape and rejects empty names while allowing empty descriptions", async () => {
    await open();
    const node = document.querySelector('[data-aw-node="a"]')!;
    fireEvent.click(node.querySelector('[aria-label="Edit node name"]')!);
    fireEvent.change(screen.getByRole("textbox", { name: "Node name" }), { target: { value: "Changed" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Node name" }), { key: "Escape" });
    expect(api.save_pipeline).not.toHaveBeenCalled();
    expect(screen.getByText("Pause")).toBeTruthy();
    fireEvent.click(node.querySelector('[aria-label="Edit node name"]')!);
    fireEvent.change(screen.getByRole("textbox", { name: "Node name" }), { target: { value: " " } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Node name" }), { key: "Enter" });
    expect(api.save_pipeline).not.toHaveBeenCalled();
    fireEvent.click(node.querySelector('[aria-label="Edit node description"]')!);
    fireEvent.change(screen.getByRole("textbox", { name: "Node description" }), { target: { value: "" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Node description" }));
    await waitFor(() => expect(saved.graph.nodes[1].description).toBe(""));
  });
  it("keeps newer settings edits when an inline save completes late", async () => {
    await open();
    let finish!: (result: { pipeline: AutomationDto }) => void;
    api.save_pipeline.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(document.querySelector('[data-aw-node="a"] [aria-label="Edit node name"]')!);
    fireEvent.change(screen.getByRole("textbox", { name: "Node name" }), { target: { value: "Wait for UEFN" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Node name" }), { key: "Enter" });
    await waitFor(() => expect(api.save_pipeline).toHaveBeenCalledTimes(1));
    const submitted = structuredClone(api.save_pipeline.mock.calls[0][0]);
    editNode();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seconds" }), { target: { value: "5" } });
    await act(async () => { finish({ pipeline: submitted }); });
    expect((screen.getByRole("spinbutton", { name: "Seconds" }) as HTMLInputElement).value).toBe("5");
    api.save_pipeline.mockClear();
    await save();
    expect(saved.graph.nodes[1].config.seconds).toBe(5);
    expect(saved.graph.nodes[1].label).toBe("Wait for UEFN");
  });
  it("shows failed inline saves and allows retrying without losing edits", async () => {
    await open();
    api.save_pipeline.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(document.querySelector('[data-aw-node="a"] [aria-label="Edit node name"]')!);
    fireEvent.change(screen.getByRole("textbox", { name: "Node name" }), { target: { value: "Wait for UEFN" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Node name" }), { key: "Enter" });
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(saved.graph.nodes[1].label).toBe("Wait for UEFN");
  });
});

describe("workflow multi-selection and groups", () => {
  const canvas = () => document.querySelector('.aw-board')!;
  const node = (id: string) => document.querySelector(`.aw-node[data-aw-node="${id}"]`)!;
  const selected = () => [...document.querySelectorAll('.aw-node.is-selected')].map((el) => el.getAttribute('data-aw-node'));
  const ctrlClick = (id: string) => {
    fireEvent.pointerDown(node(id), { button: 0, ctrlKey: true, pointerId: 7 });
    fireEvent.pointerUp(canvas(), { button: 0, ctrlKey: true, pointerId: 7 });
  };
  const shortcut = (shiftKey = false) => fireEvent.keyDown(canvas(), { key: 'g', ctrlKey: true, shiftKey });
  async function makeGroup() {
    await open();
    ctrlClick('s'); ctrlClick('a'); shortcut();
    await waitFor(() => expect(saved.graph.groups?.[0].node_ids).toEqual(['s', 'a']));
  }

  it("toggles Ctrl-click selection, including on editable node titles without editing", async () => {
    await open();
    ctrlClick('s'); ctrlClick('a');
    expect(selected()).toEqual(['s', 'a']);
    ctrlClick('s');
    expect(selected()).toEqual(['a']);
    const title = node('b').querySelector('.aw-inline-text')!;
    fireEvent.pointerDown(title, { button: 0, ctrlKey: true });
    fireEvent.click(title, { ctrlKey: true });
    expect(selected()).toEqual(['a', 'b']);
    expect(screen.queryByRole('textbox', { name: 'Node name' })).toBeNull();
    expect(api.save_pipeline).not.toHaveBeenCalled();
  });

  it("box-selects backwards at non-default zoom without panning or moving nodes", async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    const transform = (document.querySelector('.aw-world') as HTMLElement).style.transform;
    const zoom = 1 / 1.2;
    const start = { button: 0, ctrlKey: true, shiftKey: true, pointerId: 4, clientX: 280 + 520 * zoom, clientY: 160 + 100 * zoom };
    const end = { ...start, clientX: 280 - 20 * zoom, clientY: 160 - 20 * zoom };
    fireEvent.pointerDown(canvas(), start);
    fireEvent.pointerMove(canvas(), end);
    expect(document.querySelector('.aw-selection-box')).toBeTruthy();
    expect(selected()).toEqual(['s', 'a']);
    fireEvent.pointerUp(canvas(), end);
    expect(document.querySelector('.aw-selection-box')).toBeNull();
    expect((document.querySelector('.aw-world') as HTMLElement).style.transform).toBe(transform);
    shortcut();
    await waitFor(() => expect(saved.graph.groups?.[0].node_ids).toEqual(['s', 'a']));
    expect(saved.graph.nodes.map(({ x, y }) => [x, y])).toEqual([[0, 0], [280, 0], [560, 0]]);
  });

  it.each(['pointercancel', 'Escape', 'blur'])("cancels box selection on %s and restores the prior selection", async (end) => {
    await open(); ctrlClick('b');
    fireEvent.pointerDown(canvas(), { button: 0, ctrlKey: true, shiftKey: true, pointerId: 4, clientX: 260, clientY: 140 });
    fireEvent.pointerMove(canvas(), { pointerId: 4, clientX: 810, clientY: 260 });
    expect(selected()).toEqual(['s', 'a', 'b']);
    if (end === 'pointercancel') fireEvent.pointerCancel(canvas(), { pointerId: 4 });
    else if (end === 'blur') fireEvent.blur(window);
    else fireEvent.keyDown(canvas(), { key: 'Escape' });
    expect(selected()).toEqual(['b']);
    expect(document.querySelector('.aw-selection-box')).toBeNull();
  });

  it("drags all selected nodes together while leaving unselected nodes alone", async () => {
    await open(); ctrlClick('s'); ctrlClick('a');
    fireEvent.pointerDown(node('a').querySelector('.aw-node-body')!, { button: 0, pointerId: 3, clientX: 580, clientY: 180 });
    fireEvent.pointerMove(canvas(), { pointerId: 3, clientX: 660, clientY: 220 });
    fireEvent.pointerUp(canvas(), { pointerId: 3, clientX: 660, clientY: 220 });
    expect(selected()).toEqual(['s', 'a']);
    await save();
    expect(saved.graph.nodes.map(({ x, y }) => [x, y])).toEqual([[80, 40], [360, 40], [560, 0]]);
  });

  it("persists a group, edits its outside name, and retains it on reload", async () => {
    await makeGroup();
    expect(document.querySelector('.aw-group-title .aw-inline-text')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Edit group name' }));
    const input = screen.getByRole('textbox', { name: 'Group name' });
    fireEvent.change(input, { target: { value: 'Island setup' } });
    fireEvent.keyDown(input, { key: 'g', ctrlKey: true, shiftKey: true });
    expect(saved.graph.groups).toHaveLength(1);
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(saved.graph.groups?.[0].name).toBe('Island setup'));
    fireEvent.click(screen.getByText('Example'));
    await screen.findByRole('button', { name: 'Select group Island setup' });
    expect(selected()).toEqual([]);
  });

  it("removes only a selected member, shrinks the box, then removes an empty group", async () => {
    await makeGroup();
    expect((document.querySelector('.aw-group') as HTMLElement).style.width).toBe('528px');
    fireEvent.pointerDown(node('a').querySelector('.aw-node-body')!, { button: 0, pointerId: 3 });
    fireEvent.pointerUp(canvas(), { button: 0, pointerId: 3 });
    expect(selected()).toEqual(['a']);
    shortcut(true);
    await waitFor(() => expect(saved.graph.groups?.[0].node_ids).toEqual(['s']));
    expect((document.querySelector('.aw-group') as HTMLElement).style.width).toBe('248px');
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Select group Group' }), { button: 0, pointerId: 5 });
    fireEvent.pointerUp(canvas(), { pointerId: 5 });
    shortcut(true);
    await waitFor(() => expect(saved.graph.groups).toEqual([]));
    expect(document.querySelector('.aw-group')).toBeNull();
    expect(saved.graph.nodes).toHaveLength(3);
    expect(saved.graph.edges).toHaveLength(1);
  });

  it("moves a group as a unit, updates its box, and ungroups all members", async () => {
    await makeGroup();
    const group = screen.getByRole('button', { name: 'Select group Group' });
    fireEvent.pointerDown(group, { button: 0, pointerId: 5, clientX: 260, clientY: 140 });
    fireEvent.pointerMove(canvas(), { pointerId: 5, clientX: 300, clientY: 200 });
    fireEvent.pointerUp(canvas(), { pointerId: 5, clientX: 300, clientY: 200 });
    expect((group as HTMLElement).style.left).toBe('16px');
    expect((group as HTMLElement).style.top).toBe('36px');
    shortcut(true);
    await waitFor(() => expect(saved.graph.groups).toEqual([]));
    expect(saved.graph.nodes.map(({ x, y }) => [x, y])).toEqual([[40, 60], [320, 60], [560, 0]]);
  });

  it("keeps names readable as zoom decreases and cleans membership when a node is deleted", async () => {
    await makeGroup();
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    expect((document.querySelector('.aw-group-title') as HTMLElement).style.transform).toBe('scale(1.2)');
    fireEvent.click(screen.getByRole('button', { name: 'Delete Pause' }));
    await save();
    expect(saved.graph.groups?.[0].node_ids).toEqual(['s']);
    expect((document.querySelector('.aw-group') as HTMLElement).style.width).toBe('248px');
  });

  it("reports group save failures and keeps the group for a retry", async () => {
    await open();
    api.save_pipeline.mockRejectedValueOnce(new Error('offline'));
    ctrlClick('s'); ctrlClick('a'); shortcut();
    await screen.findByRole('alert');
    expect(document.querySelector('.aw-group')).toBeTruthy();
    await save();
    await waitFor(() => expect(saved.graph.groups?.[0].node_ids).toEqual(['s', 'a']));
  });
});


describe("workflow history controls", () => {
  it("shows only the workflow name and supports keyboard undo/redo after saving", async () => {
    await open();
    expect(screen.queryByLabelText("Workflow description")).toBeNull();
    expect(screen.getByRole("button", { name: "Undo", exact: true }).hasAttribute("disabled")).toBe(true);
    const name = screen.getByRole("textbox", { name: "Workflow name" });
    fireEvent.focus(name);
    fireEvent.change(name, { target: { value: "Ren" } });
    fireEvent.change(name, { target: { value: "Renamed" } });
    fireEvent.blur(name);
    await waitFor(() => expect(saved.name).toBe("Renamed"));
    const board = document.querySelector(".aw-board")!;
    fireEvent.keyDown(board, { key: "z", ctrlKey: true });
    await waitFor(() => expect(saved.name).toBe("Example"));
    fireEvent.keyDown(board, { key: "y", ctrlKey: true });
    await waitFor(() => expect(saved.name).toBe("Renamed"));
    fireEvent.keyDown(name, { key: "z", ctrlKey: true });
    expect((name as HTMLInputElement).value).toBe("Renamed");
  });

  it("undoes an entire drag once and invalidates redo after a new edit", async () => {
    await open();
    const node = document.querySelector('[data-aw-node="a"] .aw-node-body')!;
    const board = document.querySelector(".aw-board")!;
    fireEvent.pointerDown(node, { button: 0, pointerId: 1, clientX: 600, clientY: 200 });
    fireEvent.pointerMove(board, { pointerId: 1, clientX: 620, clientY: 200 });
    fireEvent.pointerMove(board, { pointerId: 1, clientX: 640, clientY: 200 });
    fireEvent.pointerUp(board, { pointerId: 1, clientX: 640, clientY: 200 });
    fireEvent.keyDown(board, { key: "z", ctrlKey: true });
    await waitFor(() => expect(api.save_pipeline).toHaveBeenCalled());
    expect(saved.graph.nodes[1].x).toBe(280);
    expect(screen.getByRole("button", { name: "Undo", exact: true }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Enabled", exact: true }));
    expect(screen.getByRole("button", { name: "Redo", exact: true }).hasAttribute("disabled")).toBe(true);
  });

  it("restores saved versions as undoable new saves, retaining run history", async () => {
    saved.runs = [{ ok: true, steps: [] }];
    const old = { ...structuredClone(saved), name: "Earlier", graph: { ...saved.graph, groups: [{ id: "g", name: "Setup", node_ids: ["a", "b"] }] } };
    api.list_workflow_versions.mockResolvedValue({ ok: true, versions: [{ id: "v1", name: "Earlier", saved_at: 100, node_count: 3 }] });
    api.get_workflow_version.mockResolvedValue({ ok: true, workflow: old });
    await open();
    dropdown("History");
    fireEvent.click(await screen.findByRole("radio", { name: /Version 1 · Earlier/ }));
    await waitFor(() => expect(saved.name).toBe("Earlier"));
    expect(saved.graph.groups?.[0].name).toBe("Setup");
    expect(saved.runs).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Undo", exact: true }));
    await waitFor(() => expect(saved.name).toBe("Example"));
    expect(saved.graph.groups).toBeUndefined();
  });

  it("does not mix histories between pipeline and automation with the same id", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Enabled", exact: true }));
    fireEvent.click(screen.getByText("Daily check"));
    await screen.findByDisplayValue("Daily check");
    expect(screen.getByRole("button", { name: "Undo", exact: true }).hasAttribute("disabled")).toBe(true);
  });
});
