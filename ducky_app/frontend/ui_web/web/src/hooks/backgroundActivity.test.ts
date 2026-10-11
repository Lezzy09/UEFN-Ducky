import { afterEach, describe, expect, it } from "vitest";
import {
  _peekBackgroundJobsForTests,
  _resetBackgroundActivityForTests,
  clearFinishedBackgroundJobs,
  countWorkingBackgroundJobs,
  dismissBackgroundJob,
  onBackgroundJobEnded,
  upsertBackgroundJob,
} from "./backgroundActivity";

afterEach(() => {
  _resetBackgroundActivityForTests();
});

describe("backgroundActivity", () => {
  it("upserts live progress then keeps finished history", () => {
    upsertBackgroundJob({
      id: "ollama-pull:1",
      source: "ollama",
      title: "Download qwen",
      percent: 10,
      phase: "working",
    });
    const done = upsertBackgroundJob({
      id: "ollama-pull:1",
      percent: 100,
      phase: "done",
      detail: "ready",
    });
    expect(done.title).toBe("Download qwen");
    expect(done.phase).toBe("done");
    expect(countWorkingBackgroundJobs(_peekBackgroundJobsForTests())).toBe(0);
    expect(_peekBackgroundJobsForTests()[0]?.detail).toBe("ready");
  });

  it("ignores idle ready-to-run spam", () => {
    upsertBackgroundJob({
      id: "graph:idle",
      title: "Image to island",
      phase: "ready",
      detail: "Ready to run",
    });
    expect(_peekBackgroundJobsForTests().some((j) => j.phase === "ready")).toBe(false);
  });

  it("clearFinished keeps only working jobs", () => {
    upsertBackgroundJob({ id: "a", title: "A", phase: "working" });
    upsertBackgroundJob({ id: "b", title: "B", phase: "done" });
    clearFinishedBackgroundJobs();
    dismissBackgroundJob("missing");
    const jobs = _peekBackgroundJobsForTests();
    expect(jobs.map((j) => j.id)).toEqual(["a"]);
    expect(countWorkingBackgroundJobs(jobs)).toBe(1);
  });
});

describe("onBackgroundJobEnded", () => {
  it("reports a job that worked and ended, once, and a throwing listener breaks nothing", () => {
    const ended: Array<[string, string, number]> = [];
    const stopThrow = onBackgroundJobEnded(() => {
      throw new Error("listener bug");
    });
    const stop = onBackgroundJobEnded((job, seconds) => ended.push([job.id, job.phase, seconds]));
    upsertBackgroundJob({ id: "install:a", source: "store", title: "Roguelike", phase: "working", startedAt: Date.now() - 30_000 });
    upsertBackgroundJob({ id: "install:a", phase: "error", detail: "Disk full" });
    upsertBackgroundJob({ id: "install:a", phase: "error" });
    upsertBackgroundJob({ id: "install:b", source: "store", title: "Done at once", phase: "done" });
    stop();
    stopThrow();
    expect(ended.map(([id, phase]) => [id, phase])).toEqual([["install:a", "error"]]);
    expect(ended[0][2]).toBeGreaterThanOrEqual(29);
    expect(_peekBackgroundJobsForTests()[0].phase).toBe("done");
  });
});
