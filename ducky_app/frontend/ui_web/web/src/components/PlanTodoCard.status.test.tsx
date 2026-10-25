// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => undefined }));
import { PlanTodoCard, planStatusLine } from "./PlanTodoCard";
import type { ChatPlan, PlanNode } from "../types/panel";

afterEach(cleanup);
const step = (id: string, status: PlanNode["status"], extra: Partial<PlanNode> & { after?: string[] } = {}): PlanNode =>
  ({ id, content: `Step ${id}`, status, ...extra }) as PlanNode;
const plan = (nodes: PlanNode[], status = "open"): ChatPlan => ({ id: "p", chat_id: "lead", title: "Swarm", todos: [], nodes, status });
const line = (p: ChatPlan) => planStatusLine(p).map((part) => part.text).join(" · ");

describe("plan status line", () => {
  it("paused: nobody started, press Play", () => {
    const p = plan([
      { id: "a", content: "App core", status: "pending", children: [step("a1", "pending")] },
      { id: "b", content: "Agents", status: "pending", children: [step("b1", "pending")] },
    ], "paused");
    expect(line(p)).toBe("Paused · 0/4 · 2 sections, nobody started · press Play");
  });

  it("running: working, waiting on hand-offs (named on hover) and a blocked member", () => {
    const p = plan([
      { id: "h", content: "Agent host", status: "in_progress", children: [
        step("h1", "in_progress", { body_markdown: "notes\nBLOCKED: needs p4a-pipe" }),
      ] },
      { id: "w", content: "Workers", status: "in_progress", children: [step("w1", "in_progress"), step("w2", "completed")] },
      { id: "x", content: "Later", status: "pending", after: ["h"], children: [step("x1", "pending")] } as PlanNode,
    ]);
    expect(line(p)).toBe("1 working · 1 waiting on hand-offs · 1 blocked: Agent host — needs p4a-pipe · 1/7");
    expect(planStatusLine(p)[1]!.title).toBe("3 Later waits for 1");
  });

  it("done", () => {
    expect(line(plan([step("a", "completed"), step("b", "cancelled")]))).toBe("Done · 1/1");
  });

  it("renders the line in the card and a waiting row shows its blocker in grey", () => {
    const p = plan([
      { id: "a", content: "First", status: "in_progress", children: [step("a1", "in_progress")] },
      { id: "b", content: "Second", status: "pending", after: ["a1"], children: [step("b1", "pending")] } as PlanNode,
    ]);
    const { container } = render(<PlanTodoCard plan={p} />);
    expect(screen.getByRole("status").textContent).toBe("1 working · 1 waiting on hand-offs · 0/4");
    const waits = container.querySelector('[data-plan-node-id="b"] .plan-todo-waits');
    expect(waits?.textContent).toBe("waits for 1.1");
    expect(container.querySelector('[data-plan-node-id="a"] .plan-todo-waits')).toBeNull();
  });
});
