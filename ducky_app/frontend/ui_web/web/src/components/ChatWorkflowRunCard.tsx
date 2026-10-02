import { useState } from "react";

import { requestFocusGraph } from "../hooks/graphActivity";
import { getApi } from "../hooks/usePanelApi";
import {
  dismissWorkflowRun,
  useChatWorkflowRun,
  type ChatWorkflowRun,
  type ChatWorkflowStep,
} from "../hooks/workflowRunsByChat";
import { requestOpenWorkflowsTab } from "../navigation/openWorkflowsTab";

/** Yes/no gates are instant; the card lists them only when one fails. */
function shownSteps(run: ChatWorkflowRun): ChatWorkflowStep[] {
  return run.steps.filter((s) => s.type !== "logic.if" || s.state === "error");
}

export function workflowRunSummary(run: ChatWorkflowRun): string {
  const steps = shownSteps(run);
  const total = steps.filter((s) => !s.extra).length;
  if (run.state === "done") return "Finished";
  if (run.state === "stopped") return "Stopped";
  if (run.state === "error") {
    const failed = steps.find((s) => s.state === "error");
    return failed ? `Failed at ${failed.label}` : "Failed";
  }
  const current = run.steps.find((s) => s.node === run.current);
  const at = steps.findIndex((s) => s.node === run.current && !s.extra);
  const label = current?.label ?? "Starting";
  return at >= 0 && total ? `Step ${at + 1}/${total} · ${label}` : label;
}

const MARK: Record<ChatWorkflowStep["state"], string> = {
  pending: "○",
  running: "●",
  ok: "✓",
  error: "✕",
  stopped: "■",
};

/** The workflow this chat's ducky is running: name, every step, the one running now. */
export function ChatWorkflowRunCard({ chatId }: { chatId: string }) {
  const run = useChatWorkflowRun(chatId);
  const [open, setOpen] = useState(false);
  if (!run) return null;
  const steps = shownSteps(run);
  const main = steps.filter((s) => !s.extra);
  const done = main.filter((s) => s.state === "ok").length;
  const running = run.state === "running";
  const openInEditor = () => {
    requestOpenWorkflowsTab();
    requestFocusGraph(
      run.workflowId,
      run.current ? { nodes: [run.current] } : {},
    );
  };

  return (
    <div className="chat-pane-workflow-dock">
      <div
        className={`chat-plan-popup chat-workflow-run is-${run.state}`}
        data-testid="chat-workflow-run"
      >
        <div className="chat-plan-popup-bar">
          <button
            type="button"
            className="chat-plan-popup-bar-main"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            title={open ? "Hide steps" : "Show steps"}
          >
            <span className="chat-plan-popup-bar-kicker chat-workflow-run-kicker">
              Workflow
            </span>
            <span className="chat-plan-popup-bar-title">{run.name}</span>
            <span className="chat-plan-popup-bar-count chat-workflow-run-status">
              {workflowRunSummary(run)}
            </span>
            <span
              className={`chat-plan-popup-chevron${open ? " is-open" : ""}`}
              aria-hidden
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </span>
          </button>
          <button
            type="button"
            className="chat-plan-popup-bar-open"
            onClick={openInEditor}
            title="Open in Workflows"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <path d="M15 3h6v6" />
              <path d="M10 14L21 3" />
            </svg>
          </button>
          {running ? (
            <button
              type="button"
              className="chat-plan-popup-bar-stop"
              onClick={() => void getApi()?.stop_workflow?.(run.workflowId)}
              title="Stop the workflow"
              aria-label="Stop the workflow"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="currentColor"
                stroke="none"
              >
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              className="chat-plan-popup-bar-stop"
              onClick={() => dismissWorkflowRun(chatId)}
              title="Hide"
              aria-label="Hide workflow card"
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M18 6L6 18" />
                <path d="M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
        <div className="chat-workflow-run-progress" aria-hidden>
          <span
            style={{
              width: `${main.length ? Math.round((done / main.length) * 100) : 0}%`,
            }}
          />
        </div>
        {open ? (
          <ol className="chat-workflow-run-steps">
            {steps.map((s) => (
              <li
                key={s.node}
                className={`chat-workflow-run-step is-${s.state}${s.extra ? " is-extra" : ""}`}
              >
                <span className="chat-workflow-run-mark" aria-hidden>
                  {MARK[s.state]}
                </span>
                <span className="chat-workflow-run-label">{s.label}</span>
                {s.error ? (
                  <span className="chat-workflow-run-error">{s.error}</span>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </div>
  );
}
