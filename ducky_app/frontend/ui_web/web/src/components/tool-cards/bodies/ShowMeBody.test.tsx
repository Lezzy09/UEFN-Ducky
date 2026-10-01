// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("reads ducky_ui_show's plain arguments: a name with role, more ids, an action", () => {
    expect(showMeRequestFromTool("ducky_ui_show", { target: "Save", role: "button", within: "workflows.details", title: "Save" })?.target)
      .toEqual({ role: "button", name: "Save", within: "workflows.details" });
    expect(showMeRequestFromTool("ducky_ui_show", { target: "Run log", role: "text", title: "Log" })?.target).toEqual({ text: "Run log" });
    expect(showMeRequestFromTool("ducky_ui_show", { target: "workflows.node.a", also: ["workflows.node.b"], title: "Both" })?.target)
      .toEqual(["workflows.node.a", "workflows.node.b"]);
    expect(showMeRequestFromTool("ducky_ui_show", { target: "workflows.palette.flow.repeat", action: "workflows.add_menu", action_args: { query: "repeat" }, title: "Repeat" })?.action)
      .toEqual({ id: "workflows.add_menu", args: { query: "repeat" } });
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
