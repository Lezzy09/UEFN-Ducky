// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatPlan, PlanProgress } from "../types/panel";
const api = vi.hoisted(() => ({
  list_all_conversations: async () => [{ id: "lead", title: "Swarm Speed Developer" }],
  get_plan: async () => ({ plan: null }),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => null }));
import { ChatPlanCard } from "./ChatPlanCard";

const plan: ChatPlan = {
  id: "plan", chat_id: "solo", title: "Ship the split", status: "open", todos: [],
  nodes: [{ id: "a", content: "Step A", status: "pending", children: [] }],
};
const progress: PlanProgress = { total: 1, completed: 0, pending: 1, in_progress: 0, cancelled: 0 };
const noop = () => {};

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("docks an open plan above the composer", () => {
  const { container } = render(
    <ChatPlanCard plan={plan} progress={progress} allDone={false} onOpenPlan={noop} onStopTracking={noop} onOpenFile={noop} />,
  );
  expect(container.querySelector(".chat-pane-plan-dock")).toBeTruthy();
  expect(screen.getAllByText("Ship the split").length).toBeGreaterThan(0);
});

it("a member's card links to its lead and the full plan; a lead's card does not", async () => {
  const member: ChatPlan = {
    ...plan,
    assigned_from: { chat_id: "lead", node_id: "section", plan_title: "Master", assignee: "builder" },
  };
  const { rerender } = render(
    <ChatPlanCard plan={member} progress={progress} allDone={false} onOpenPlan={noop} onStopTracking={noop} onOpenFile={noop} />,
  );
  expect(await screen.findByText("Lead: Swarm Speed Developer")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Full plan" })).toBeTruthy();

  rerender(<ChatPlanCard plan={plan} progress={progress} allDone={false} onOpenPlan={noop} onStopTracking={noop} onOpenFile={noop} />);
  expect(screen.queryByRole("navigation", { name: "Lead plan" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Full plan" })).toBeNull();
});

it("shows nothing once the plan is finished or gone", () => {
  const done = render(
    <ChatPlanCard plan={plan} progress={progress} allDone onOpenPlan={noop} onStopTracking={noop} onOpenFile={noop} />,
  );
  expect(done.container.innerHTML).toBe("");
  const none = render(
    <ChatPlanCard plan={null} progress={null} allDone={false} onOpenPlan={noop} onStopTracking={noop} onOpenFile={noop} />,
  );
  expect(none.container.innerHTML).toBe("");
});
