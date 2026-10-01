import { afterEach, describe, expect, it } from "vitest";
import {
  _peekBackgroundJobsForTests,
  _resetBackgroundActivityForTests,
} from "./backgroundActivity";
import { registerOpenWorkflowsTab } from "../navigation/openWorkflowsTab";
import {
  applyBackgroundJobPush,
  applyGraphFocusPush,
  graphJobId,
  requestFocusGraph,
  takePendingGraphFocus,
  takePendingGraphFocusTarget,
  workflowIdFromJobId,
  syncReadyGraphJobs,
} from "./graphActivity";

afterEach(() => {
  takePendingGraphFocus();
  _resetBackgroundActivityForTests();
});

describe("graphActivity", () => {
  it("does not list idle graphs as ready to run", () => {
    applyBackgroundJobPush({
      type: "background_job",
      id: graphJobId("idle"),
      title: "Image to island",
      phase: "ready",
      detail: "Ready to run",
    });
    syncReadyGraphJobs(
      [
        { id: "idle", name: "Image to island", enabled: true, node_count: 3 },
        { id: "a", name: "Nightly", enabled: true, node_count: 2 },
      ],
      _peekBackgroundJobsForTests(),
    );
    expect(_peekBackgroundJobsForTests().some((j) => j.phase === "ready")).toBe(false);
  });

  it("does not clobber a running graph with ready", () => {
    applyBackgroundJobPush({
      type: "background_job",
      id: graphJobId("a"),
      title: "Nightly",
      phase: "working",
      detail: "Running",
    });
    syncReadyGraphJobs(
      [{ id: "a", name: "Nightly", enabled: true, node_count: 2 }],
      _peekBackgroundJobsForTests(),
    );
    expect(_peekBackgroundJobsForTests()[0]?.phase).toBe("working");
  });

  it("parses workflow id from live and finished job ids", () => {
    expect(workflowIdFromJobId(graphJobId("abc"))).toBe("abc");
    expect(workflowIdFromJobId("graph-run:abc:171000")).toBe("abc");
  });

  it("opens the Workflows editor when chat saves a workflow", () => {
    let opened = 0;
    const stop = registerOpenWorkflowsTab(() => {
      opened += 1;
    });
    applyGraphFocusPush({ type: "graph_focus", id: "p1", action: "saved" });
    expect(opened).toBe(1);
    expect(takePendingGraphFocus()).toBe("p1");
    stop();
  });

  it("drops a queued focus when chat deletes that workflow", () => {
    applyGraphFocusPush({ type: "graph_focus", id: "a1", action: "saved" });
    applyGraphFocusPush({ type: "graph_focus", id: "a1", action: "deleted" });
    expect(takePendingGraphFocus()).toBe("");
  });

  it("queues a graph focus for the editor", () => {
    requestFocusGraph("play");
    expect(takePendingGraphFocus()).toBe("play");
    expect(takePendingGraphFocus()).toBe("");
  });

  it("carries the nodes and caption an agent is showing", () => {
    applyGraphFocusPush({ type: "graph_focus", id: "p1", action: "show", nodes: ["a", "b"], select: true, note: "This checks the score" });
    expect(takePendingGraphFocusTarget()).toEqual({ id: "p1", nodes: ["a", "b"], select: true, note: "This checks the score" });
    expect(takePendingGraphFocusTarget()).toBeNull();
  });
});
