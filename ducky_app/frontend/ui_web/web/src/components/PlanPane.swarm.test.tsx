// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ onEvent: () => {}, onStatus: vi.fn(() => () => {}) }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => transport }));
vi.mock("../hooks/perfMonitor", () => ({
  installPerfMonitor: () => {}, noteFrameDelivery: () => {}, notePendingDepth: () => {},
}));
const api = vi.hoisted(() => ({ get_plan: vi.fn(), swarm_suggest: vi.fn() }));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false }));
vi.mock("./ducky/DuckyProfileModal", () => ({ DuckyProfileModal: () => null }));

import { PlanPane } from "./PlanPane";
import fixture from "../swarm/fixtures/swarm_builder.json";

const plan = (assignee?: string) => ({
  id: "p1", chat_id: "lead", title: "Inventory UI", status: "paused", todos: [],
  nodes: ["Grid", "Tooltips"].map((name, i) => ({
    id: `s${i}`, content: name, status: "pending", assignee,
    children: [{ id: `s${i}a`, content: `${name} step`, status: "pending" }],
  })),
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Run as a swarm", () => {
  it("a suggestion shows the button, and pressing it opens the Swarm builder card", async () => {
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: null });
    api.swarm_suggest.mockResolvedValue({ ok: true, suggestion: fixture });
    render(<PlanPane chatId="lead" />);
    const button = await screen.findByRole("button", { name: `Run as a swarm (${fixture.seats.length} agents)` });
    expect(api.swarm_suggest).toHaveBeenCalledWith("lead", null);
    expect(screen.queryByRole("region", { name: /Build swarm/ })).toBeNull();
    fireEvent.click(button);
    expect(screen.getByRole("region", { name: "Build swarm: Shop island" })).toBeTruthy();
  });

  it("no suggestion, no button", async () => {
    api.get_plan.mockResolvedValue({ ok: true, plan: plan(), progress: null });
    api.swarm_suggest.mockResolvedValue({ ok: true, suggestion: null });
    render(<PlanPane chatId="lead" />);
    await waitFor(() => expect(api.swarm_suggest).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Run as a swarm/ })).toBeNull();
  });

  it("a plan a team already works on never asks", async () => {
    api.get_plan.mockResolvedValue({ ok: true, plan: plan("group-a"), progress: null });
    render(<PlanPane chatId="lead" />);
    await screen.findByRole("heading", { name: "Inventory UI" });
    expect(api.swarm_suggest).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Run as a swarm/ })).toBeNull();
  });
});
