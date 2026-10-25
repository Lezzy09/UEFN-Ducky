// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ onEvent: () => {}, onStatus: vi.fn(() => () => {}) }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => transport }));
vi.mock("../hooks/perfMonitor", () => ({
  installPerfMonitor: () => {}, noteFrameDelivery: () => {}, notePendingDepth: () => {},
}));
const api = vi.hoisted(() => ({ get_plan: vi.fn(), plan_launch: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
vi.mock("./ducky/DuckyProfileModal", () => ({ DuckyProfileModal: () => null }));

import { PlanPane } from "./PlanPane";

const plan = (planned?: string, assignee?: string) => ({
  id: "p1", chat_id: "lead", title: "Team plan", status: "paused", todos: [],
  nodes: [
    { id: "a", content: "Tool server", status: "pending", planned_assignee: planned, assignee, children: [{ id: "a1", content: "Step", status: "pending" }] },
    { id: "b", content: "Agent host", status: "pending", children: [{ id: "b1", content: "Step", status: "pending" }] },
  ],
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Launch team", () => {
  it("is hidden while no sub plan has a planned owner", async () => {
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: null });
    render(<PlanPane chatId="lead" />);
    await screen.findByRole("heading", { name: "Team plan" });
    expect(screen.queryByRole("button", { name: /Launch team/ })).toBeNull();
  });

  it("confirms who gets which section, then calls plan_launch once and shows seating", async () => {
    api.get_plan.mockResolvedValue({ ok: true, plan: plan("tool-dev"), progress: null });
    let finish!: (value: unknown) => void;
    api.plan_launch.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<PlanPane chatId="lead" />);
    fireEvent.click(await screen.findByRole("button", { name: "Launch team (1 agent)" }));
    const confirm = screen.getByRole("region", { name: "Launch team" });
    expect(confirm.textContent).toContain("Tool server");
    expect(confirm.textContent).toContain("Agent host · nobody yet");
    fireEvent.click(screen.getByRole("button", { name: "Launch 1 agent" }));
    expect(api.plan_launch).toHaveBeenCalledTimes(1);
    expect(api.plan_launch).toHaveBeenCalledWith("lead");
    expect(screen.getByRole("button", { name: "Seating 0 of 1…" })).toBeTruthy();
    api.get_plan.mockResolvedValue({ ok: true, plan: plan("tool-dev", "group-a"), progress: null });
    await act(async () => finish({ ok: true, seated: ["Tool server dev"], failed: [] }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Launch team|Seating/ })).toBeNull());
    expect(api.plan_launch).toHaveBeenCalledTimes(1);
  });
});
