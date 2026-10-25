import { subscribeAgentEvents } from "./useAgentEventBus";
import { getApi } from "./usePanelApi";

/** A job pushes bridge_job_progress when it ends; this slow poll only covers a lost push. */
const FALLBACK_POLL_MS = 5000;
/** One early look: most jobs (key checks, small reads) are done within 100 ms. */
const FIRST_POLL_MS = 100;
const FINAL_STATES = new Set(["done", "error", "cancelled"]);

/**
 * Run an allowlisted PanelApi method on a Python worker thread. Looks once after
 * 100 ms, then waits for the job's final `bridge_job_progress` push and reads the result
 * with one `bridge_job_poll` (a poll every 5 s backs up a missed push), so the pywebview bridge stays free.
 */
export async function runBridgeJob<T = Record<string, unknown>>(
  name: string,
  args: unknown[] = [],
  timeoutMs = 180_000,
): Promise<T> {
  const api = getApi() as Record<string, unknown> | null;
  if (!api) throw new Error("Panel API unavailable");

  const start = api.bridge_job_start as
    | ((n: string, a?: unknown[]) => Promise<Record<string, unknown>>)
    | undefined;
  const poll = api.bridge_job_poll as
    | ((id: string) => Promise<Record<string, unknown>>)
    | undefined;

  if (start && poll) {
    // Listen before starting: an instant job can push "done" before start() answers.
    const finished = new Set<string>();
    let wake: (() => void) | null = null;
    const unsubscribe = subscribeAgentEvents((event) => {
      const ev = event as { type: string; job_id?: string; state?: string };
      if (ev.type !== "bridge_job_progress" || !ev.job_id || !FINAL_STATES.has(String(ev.state))) return;
      finished.add(ev.job_id);
      wake?.();
    });
    try {
      const started = await start(name, args);
      if (!started?.ok || !started.job_id) {
        throw new Error(String(started?.error || `${name} failed to start`));
      }
      const jobId = String(started.job_id);
      const deadline = Date.now() + timeoutMs;
      let wait = FIRST_POLL_MS;
      while (Date.now() < deadline) {
        if (!finished.has(jobId)) {
          await new Promise<void>((resolve) => {
            const timer = setTimeout(done, Math.min(wait, Math.max(0, deadline - Date.now())));
            function done() {
              clearTimeout(timer);
              wake = null;
              resolve();
            }
            wake = () => { if (finished.has(jobId)) done(); };
          });
        }
        wait = FALLBACK_POLL_MS;
        const polled = await poll(jobId);
        if (polled?.pending) {
          finished.delete(jobId);
          continue;
        }
        // Non-dict Python returns arrive as { ok, result }.
        if (polled && "result" in polled && polled.result !== undefined) {
          return polled.result as T;
        }
        return polled as T;
      }
      throw new Error(`${name} timed out after ${Math.round(timeoutMs / 1000)}s`);
    } finally {
      unsubscribe();
    }
  }

  // Older app builds: call the sync method directly (blocks bridge).
  const fn = api[name];
  if (typeof fn !== "function") {
    throw new Error(`${name} unavailable — rebuild the app`);
  }
  return (await (fn as (...a: unknown[]) => Promise<T>).apply(api, args)) as T;
}
