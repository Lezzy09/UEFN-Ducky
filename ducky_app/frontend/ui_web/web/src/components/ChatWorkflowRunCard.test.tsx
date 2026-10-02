// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../hooks/useAgentEventBus", () => ({
  subscribeAgentEvents: () => () => {},
}));
vi.mock("../hooks/usePanelPushBus", () => ({
  subscribePanelPush: () => () => {},
}));

import {
  applyWorkflowEvent,
  resetWorkflowRunsForTests,
} from "../hooks/workflowRunsByChat";
import { ChatWorkflowRunCard } from "./ChatWorkflowRunCard";

const plan = [
  { node: "s", label: "Start demo", type: "start.chat" },
  { node: "build", label: "Build Verse", type: "pipeline.agent" },
  { node: "ok", label: "build_ok", type: "logic.if" },
  { node: "launch", label: "Launch session", type: "pipeline.agent" },
  { node: "f", label: "End", type: "flow.end" },
];

function start(conv = "chat-1", run = "r1") {
  applyWorkflowEvent({
    type: "workflow_run",
    id: "wf-1",
    run,
    state: "started",
    conv,
    name: "Tycoony demo",
    plan,
  });
}

function step(
  node: string,
  state: string,
  extra: Record<string, string> = {},
  run = "r1",
) {
  applyWorkflowEvent({
    type: "workflow_step",
    id: "wf-1",
    run,
    node,
    state,
    ...extra,
  });
}

describe("ChatWorkflowRunCard", () => {
  afterEach(() => {
    cleanup();
    act(() => resetWorkflowRunsForTests());
  });

  it("shows the workflow this chat started and the step it is on", () => {
    render(<ChatWorkflowRunCard chatId="chat-1" />);
    act(() => {
      start();
      step("s", "running");
      step("s", "ok");
      step("build", "running");
      step("build", "running"); // the same event from the other bus
    });
    expect(screen.getByText("Tycoony demo")).toBeTruthy();
    expect(
      screen.getByText(/^Step 2\/4 · Build Verse · \d+:\d{2}$/),
    ).toBeTruthy();
    fireEvent.click(screen.getByTitle("Show steps"));
    const rows = screen
      .getAllByRole("listitem")
      .map((li) => [
        li.querySelector(".chat-workflow-run-label")?.textContent,
        ["ok", "running", "pending"].find((s) =>
          li.classList.contains(`is-${s}`),
        ),
        li.classList.contains("is-current"),
      ]);
    expect(rows).toEqual([
      ["Start demo", "ok", false],
      ["Build Verse", "running", true],
      ["Launch session", "pending", false],
      ["End", "pending", false],
    ]);
  });

  it("names the failed step and lists the failure branch that ran", () => {
    render(<ChatWorkflowRunCard chatId="chat-1" />);
    act(() => {
      start();
      step("build", "ok");
      step("ok", "error", { error: "Verse still has 3 errors" });
      step("report", "running", { label: "Report build blocker" });
      step("report", "ok");
      applyWorkflowEvent({
        type: "workflow_run",
        id: "wf-1",
        run: "r1",
        state: "error",
        error: "build_ok failed",
      });
    });
    expect(screen.getByText("Failed at build_ok")).toBeTruthy();
    fireEvent.click(screen.getByTitle("Show steps"));
    expect(screen.getByText("Verse still has 3 errors")).toBeTruthy();
    expect(screen.getByText("Report build blocker")).toBeTruthy();
    expect(screen.getByTitle("Hide")).toBeTruthy(); // finished: no Stop
  });

  it("keeps showing a Repeat as current while its inner step finishes", () => {
    render(<ChatWorkflowRunCard chatId="chat-1" />);
    act(() => {
      applyWorkflowEvent({
        type: "workflow_run",
        id: "wf-1",
        run: "r1",
        state: "started",
        conv: "chat-1",
        name: "Tycoony demo",
        plan: [
          { node: "loop", label: "Build → fix (4 tries)", type: "flow.repeat" },
          { node: "build", label: "Build Verse", type: "tool.call" },
        ],
      });
      step("loop", "running");
      step("build", "running");
      step("build", "ok");
    });
    expect(
      screen.getByText(/^Step 1\/2 · Build → fix \(4 tries\) · \d+:\d{2}$/),
    ).toBeTruthy();
  });

  it("only shows on the chat that started the run", () => {
    render(<ChatWorkflowRunCard chatId="chat-2" />);
    act(() => start("chat-1"));
    expect(screen.queryByTestId("chat-workflow-run")).toBeNull();
  });

  it("finishes and can be hidden", () => {
    render(<ChatWorkflowRunCard chatId="chat-1" />);
    act(() => {
      start();
      step("f", "ok");
      applyWorkflowEvent({
        type: "workflow_run",
        id: "wf-1",
        run: "r1",
        state: "done",
      });
    });
    expect(screen.getByText(/^Finished · \d+:\d{2}$/)).toBeTruthy();
    fireEvent.click(screen.getByTitle("Hide"));
    expect(screen.queryByTestId("chat-workflow-run")).toBeNull();
  });
});
