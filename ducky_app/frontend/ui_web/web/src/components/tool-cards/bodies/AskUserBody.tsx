import { useMemo } from "react";
import type { ToolCardBodyProps } from "../toolCardTypes";

export type AnswerRow = {
  id: string;
  prompt: string;
  summary: string;
  /** waiting | answered | skipped | failed (the tool refused, nothing was asked) */
  status: "waiting" | "answered" | "skipped" | "failed";
};

type QuestionRow = {
  id: string;
  prompt: string;
  options: Array<{ id: string; label: string }>;
};

function questionsFromArgs(args: Record<string, unknown>): QuestionRow[] {
  if (!Array.isArray(args.questions)) return [];
  const out: QuestionRow[] = [];
  for (const row of args.questions) {
    if (!row || typeof row !== "object") continue;
    const q = row as { id?: unknown; prompt?: unknown; options?: unknown };
    const id = String(q.id || "").trim();
    const prompt = String(q.prompt || "").trim();
    if (!id) continue;
    const options: Array<{ id: string; label: string }> = [];
    if (Array.isArray(q.options)) {
      for (const opt of q.options) {
        if (!opt || typeof opt !== "object") continue;
        const o = opt as { id?: unknown; label?: unknown };
        const oid = String(o.id || "").trim();
        if (!oid) continue;
        options.push({ id: oid, label: String(o.label || oid).trim() || oid });
      }
    }
    out.push({ id, prompt: prompt || id, options });
  }
  return out;
}

function labelForSelected(
  selected: string[],
  options: Array<{ id: string; label: string }>,
): string {
  const byId = new Map(options.map((o) => [o.id, o.label]));
  return selected.map((id) => byId.get(id) || id).join(", ");
}

function summarizeAnswer(
  raw: unknown,
  options: Array<{ id: string; label: string }>,
): { summary: string; status: "answered" | "skipped" | "waiting" } {
  if (raw === undefined) return { summary: "Waiting…", status: "waiting" };
  if (!raw || typeof raw !== "object") return { summary: "—", status: "answered" };
  const a = raw as { selected?: unknown; text?: unknown; skipped?: unknown };
  if (a.skipped) return { summary: "Skipped", status: "skipped" };
  const selected = Array.isArray(a.selected)
    ? a.selected.map((x) => String(x)).filter(Boolean)
    : [];
  const text = String(a.text || "").trim();
  const selectedLabels = selected.length ? labelForSelected(selected, options) : "";
  if (selectedLabels && text) return { summary: `${selectedLabels} · ${text}`, status: "answered" };
  if (selectedLabels) return { summary: selectedLabels, status: "answered" };
  if (text) return { summary: text, status: "answered" };
  return { summary: "—", status: "answered" };
}

export function rowsFromAskUser(
  args: Record<string, unknown>,
  resultText: string,
  opts?: { pending?: boolean; failed?: boolean },
): AnswerRow[] {
  if (opts?.failed) {
    return questionsFromArgs(args).map((q) => ({ id: q.id, prompt: q.prompt, summary: "Not asked", status: "failed" }));
  }
  const pending = Boolean(opts?.pending);
  let questions = questionsFromArgs(args);
  let answers: Record<string, unknown> | null = null;
  try {
    let parsed = JSON.parse(resultText || "{}") as {
      answers?: Record<string, unknown>;
      questions?: unknown;
      result?: unknown;
    };
    // The tool server wraps a string return as {"result": "<json>"}; without this the
    // card never saw the answers and said Waiting… after the user had answered.
    if (typeof parsed?.result === "string" && !parsed.answers) parsed = JSON.parse(parsed.result);
    if (parsed?.answers && typeof parsed.answers === "object") {
      answers = parsed.answers;
    }
    if (!questions.length && Array.isArray(parsed?.questions)) {
      questions = questionsFromArgs({ questions: parsed.questions });
    }
  } catch {
    /* ignore */
  }

  const ids = questions.length
    ? questions.map((q) => q.id)
    : answers
      ? Object.keys(answers)
      : [];
  const promptById = new Map(questions.map((q) => [q.id, q.prompt]));
  const optionsById = new Map(questions.map((q) => [q.id, q.options]));

  return ids.map((id) => {
    const raw = answers ? answers[id] : undefined;
    const { summary, status } = pending && !answers
      ? { summary: "Waiting…", status: "waiting" as const }
      : summarizeAnswer(raw, optionsById.get(id) || []);
    return {
      id,
      prompt: promptById.get(id) || id,
      summary,
      status,
    };
  });
}

/** Why the tool refused: the error of a JSON result, else the text itself. */
export function askUserError(resultText: string): string {
  const text = (resultText || "").trim();
  try {
    const parsed = JSON.parse(text) as { error?: unknown };
    if (parsed && typeof parsed === "object" && parsed.error) return String(parsed.error);
  } catch {
    /* plain text */
  }
  return text || "The question could not be asked.";
}

export function AskUserBody({ args, resultText, showResult, isError }: ToolCardBodyProps) {
  const pending = !showResult;
  const failed = Boolean(isError && showResult);
  const rows = useMemo(
    () => rowsFromAskUser(args, resultText, { pending, failed }),
    [args, resultText, pending, failed],
  );

  if (failed) {
    return (
      <div className="tool-card-ask-user-body">
        {rows.length ? (
          <ul className="tool-card-ask-user-rows">
            {rows.map((row) => (
              <li key={row.id} className="tool-card-ask-user-row tool-card-ask-user-row--failed">
                <span className="tool-card-ask-user-q">{row.prompt}</span>
                <span className="tool-card-ask-user-a">{row.summary}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="tool-execution-card-hint">{askUserError(resultText)}</p>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <p className="tool-card-ask-user-empty">
        {pending ? "Waiting for answers…" : "No answers stored on this card."}
      </p>
    );
  }

  return (
    <div className="tool-card-ask-user-body">
      <ul className="tool-card-ask-user-rows">
        {rows.map((row) => (
          <li key={row.id} className={`tool-card-ask-user-row tool-card-ask-user-row--${row.status}`}>
            <span className="tool-card-ask-user-q">{row.prompt}</span>
            <span className="tool-card-ask-user-a">{row.summary}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
