import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ bridge_job_start: vi.fn(), bridge_job_poll: vi.fn() }));
vi.mock("./usePanelApi", () => ({ getApi: () => api }));
const bus = vi.hoisted(() => ({ handlers: new Set<(event: Record<string, unknown>) => void>() }));
vi.mock("./useAgentEventBus", () => ({
  subscribeAgentEvents: (fn: (event: Record<string, unknown>) => void) => {
    bus.handlers.add(fn);
    return () => bus.handlers.delete(fn);
  },
}));

import { runBridgeJob } from "./bridgeJobAsync";

const push = (event: Record<string, unknown>) => { for (const fn of [...bus.handlers]) fn(event); };
let done = false;

beforeEach(() => {
  vi.useFakeTimers();
  done = false;
  api.bridge_job_start.mockResolvedValue({ ok: true, job_id: "j1", pending: true });
  api.bridge_job_poll.mockImplementation(async () => (done ? { ok: true, text: "drafted" } : { ok: true, pending: true }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

it("a 2-minute job polls on its done push, not every 100 ms", async () => {
  const result = runBridgeJob("draft_skill_pack", ["x"]);
  await vi.advanceTimersByTimeAsync(2 * 60_000);
  // One early look at 100 ms, then the 5 s safety poll only.
  expect(api.bridge_job_poll.mock.calls.length).toBeLessThanOrEqual(1 + 24);
  done = true;
  push({ type: "bridge_job_progress", job_id: "other", state: "done", percent: 100 });
  push({ type: "bridge_job_progress", job_id: "j1", state: "done", percent: 100 });
  await vi.advanceTimersByTimeAsync(0);
  await expect(result).resolves.toEqual({ ok: true, text: "drafted" });
  expect(bus.handlers.size).toBe(0);
});

it("an instant job is read on the first early look", async () => {
  done = true;
  const result = runBridgeJob("test_key", []);
  await vi.advanceTimersByTimeAsync(100);
  await expect(result).resolves.toEqual({ ok: true, text: "drafted" });
  expect(api.bridge_job_poll).toHaveBeenCalledTimes(1);
});

it("a done push that lands before start() answers is not missed", async () => {
  api.bridge_job_start.mockImplementation(async () => {
    done = true;
    push({ type: "bridge_job_progress", job_id: "j1", state: "done", percent: 100 });
    return { ok: true, job_id: "j1", pending: true };
  });
  const result = runBridgeJob("test_key", []);
  await vi.advanceTimersByTimeAsync(0);
  await expect(result).resolves.toEqual({ ok: true, text: "drafted" });
  expect(api.bridge_job_poll).toHaveBeenCalledTimes(1);
});
