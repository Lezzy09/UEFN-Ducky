// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const windowReplay = vi.hoisted(() => vi.fn(async () => ({ ok: true, shown: true })));

vi.mock("../../../hooks/usePanelApi", () => ({
  getApi: () => ({ window_spotlight_replay: windowReplay }),
}));

vi.mock("../../../showme/ShowMeService", async (original) => ({
  ...(await original<typeof import("../../../showme/ShowMeService")>()),
  playShowMe: vi.fn(async () => ({ ok: true, shown: true, missing: false, target: "x" })),
}));

import { playShowMe } from "../../../showme/ShowMeService";
import { resolveToolCategory } from "../toolCategories";
import { ShowMeBody, showMeRequestFromTool } from "./ShowMeBody";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const base = { argsText: "", isSuccess: true, isError: false, showResult: true };

describe("Show me card", () => {
  it("plays it again from the chat", async () => {
    const args = { target: "workflows.toolbar.run", title: "Test", body: "Runs the workflow now." };
    render(<ShowMeBody toolName="ducky_ui_show" args={args} resultText='{"ok":true,"shown":true}' {...base} />);
    expect(screen.getByText("Test")).toBeTruthy();
    expect(screen.getByText("Runs the workflow now.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Show me/ }));
    await waitFor(() => expect(playShowMe).toHaveBeenCalledWith(expect.objectContaining({ target: "workflows.toolbar.run", title: "Test" })));
  });

  it("replays a window spotlight on the desktop, not inside the panel", async () => {
    const args = { window: "uefn", box: { x: 0.1, y: 0.2, w: 0.3, h: 0.1 }, title: "Compile", body: "Builds Verse." };
    render(<ShowMeBody toolName="ducky_ui_show" args={args} resultText='{"ok":true,"shown":true}' {...base} />);
    expect(screen.getByText("Compile")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Show me/ }));
    await waitFor(() => expect(windowReplay).toHaveBeenCalledWith(args));
    expect(playShowMe).not.toHaveBeenCalled();
  });

  it("reads ducky_ui_show's plain arguments: a name with role, more ids, an action", () => {
    expect(showMeRequestFromTool("ducky_ui_show", { target: "Save", role: "button", within: "workflows.details", title: "Save" })?.target)
      .toEqual({ role: "button", name: "Save", within: "workflows.details" });
    expect(showMeRequestFromTool("ducky_ui_show", { target: "Run log", role: "text", title: "Log" })?.target).toEqual({ text: "Run log" });
    expect(showMeRequestFromTool("ducky_ui_show", { target: "workflows.node.a", also: ["workflows.node.b"], title: "Both" })?.target)
      .toEqual(["workflows.node.a", "workflows.node.b"]);
    expect(showMeRequestFromTool("ducky_ui_show", { target: "workflows.palette.flow.repeat", action: "workflows.add_menu", action_args: { query: "repeat" }, title: "Repeat" })?.action)
      .toEqual({ id: "workflows.add_menu", args: { query: "repeat" } });
  });

  it("reads several steps and labels the card with how many", () => {
    const args = {
      steps: [
        { target: "settings.tab.store", title: "The Store", navigate: "settings.store" },
        { target: "Install", role: "button", within: "settings.store.detail", title: "Install it", click: true },
        { target: "workflows.node.a", also: ["workflows.node.b"], title: "Nodes", action: "workflows.add_menu", action_args: { query: "if" } },
      ],
    };
    const request = showMeRequestFromTool("ducky_ui_show", args)!;
    expect(request.steps?.length).toBe(3);
    expect(request.steps?.[1].target).toEqual({ role: "button", name: "Install", within: "settings.store.detail" });
    expect(request.steps?.[2].target).toEqual(["workflows.node.a", "workflows.node.b"]);
    expect(request.steps?.[2].action).toEqual({ id: "workflows.add_menu", args: { query: "if" } });
    render(<ShowMeBody toolName="ducky_ui_show" args={args} resultText='{"ok":true}' {...base} />);
    expect(screen.getByText("The Store · 3 steps")).toBeTruthy();
  });

  it("turns show_workflow into a Show me on its nodes or group", () => {
    expect(showMeRequestFromTool("show_workflow", { workflow_id: "w", node_ids: ["a", "b"], title: "These two", body: "…" })).toMatchObject({
      target: ["workflows.node.a", "workflows.node.b"], workflow_id: "w", title: "These two",
    });
    expect(showMeRequestFromTool("show_workflow", { workflow_id: "w", group_id: "g", note: "The loop" })).toMatchObject({
      target: "workflows.group.g", title: "The loop", body: "",
    });
    expect(showMeRequestFromTool("show_workflow", { workflow_id: "w" })).toBeNull();
    expect(showMeRequestFromTool("ducky_walkthrough_run", { steps: [] })).toBeNull();
  });

  it("has its own card category, and workflow tours replay like tutorials", () => {
    expect(resolveToolCategory("ducky_ui_show").id).toBe("showme");
    expect(resolveToolCategory("show_workflow").id).toBe("showme");
    expect(resolveToolCategory("tour_workflow").id).toBe("walkthrough");
  });
});
