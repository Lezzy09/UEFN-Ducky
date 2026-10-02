import { useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { getApi } from "../../../hooks/usePanelApi";
import { Icons } from "../../../icons/Icons";
import { parseShowMeRequest, playShowMe, type ShowMeRequest } from "../../../showme/ShowMeService";
import type { ToolCardBodyProps } from "../toolCardTypes";

function hasBox(row: unknown): row is Record<string, unknown> {
  return !!row && typeof row === "object" && !Array.isArray(row) && !!(row as { box?: unknown }).box && typeof (row as { box?: unknown }).box === "object";
}

/** A Show me aimed at UEFN or another program (a fraction box, not a panel id). */
function windowSpotlightRequest(args: Record<string, unknown>): ShowMeRequest | null {
  const listed = Array.isArray(args.steps) ? args.steps.filter(hasBox) : [];
  if (!hasBox(args) && !listed.length) return null;
  const first = hasBox(args) ? args : listed[0];
  const title = String(args.title || first.title || first.body || "In this window").trim();
  const body = String((hasBox(args) ? args.body : first.body) || "").trim();
  const count = (hasBox(args) ? 1 : 0) + (Array.isArray(args.steps) ? args.steps.length : 0);
  const steps = count > 1 ? Array.from({ length: count }, () => ({ target: "window", title, body })) : undefined;
  return { target: "window", title, body, ...(steps ? { steps } : {}), windowSpotlight: args };
}

/** One step of ducky_ui_show's plain arguments (target id, or role + name, also, action + action_args). */
function flatStep(args: Record<string, unknown>): Record<string, unknown> {
  const name = String(args.target ?? "").trim();
  const role = String(args.role ?? "").trim().toLowerCase();
  const within = String(args.within ?? "").trim();
  let first: unknown = args.target;  // older cards: the target as an object or a list
  if (typeof args.target === "string") {
    first = role === "text" ? { text: name, ...(within ? { within } : {}) }
      : role ? { role, name, ...(within ? { within } : {}) }
      : name;
  }
  const also = Array.isArray(args.also) ? args.also.map(String).filter(Boolean) : [];
  const action = typeof args.action === "string" && args.action.trim()
    ? { id: args.action.trim(), args: (args.action_args as Record<string, unknown>) || {} }
    : args.action;
  return { ...args, target: also.length ? [first, ...also] : first, action };
}

/** ducky_ui_show's arguments as a request: the top-level step (if any), then `steps`. */
function fromShowArgs(args: Record<string, unknown>): ShowMeRequest | null {
  const steps = Array.isArray(args.steps)
    ? args.steps.filter((s): s is Record<string, unknown> => !!s && typeof s === "object" && !Array.isArray(s)).map(flatStep)
    : [];
  const hasTop = typeof args.target === "string" ? !!args.target.trim() : !!args.target;
  return parseShowMeRequest({ ...(hasTop ? flatStep(args) : {}), steps });
}

/** "Audio settings", or "Audio settings · 3 steps". */
export function showMeLabel(request: ShowMeRequest): string {
  const n = request.steps?.length ?? 1;
  return n > 1 ? `${request.title} · ${n} steps` : request.title;
}

/** The Show me a tool call stands for: ducky_ui_show's own arguments, or show_workflow's nodes. */
export function showMeRequestFromTool(toolName: string, args: Record<string, unknown>): ShowMeRequest | null {
  if (toolName === "ducky_ui_show") return windowSpotlightRequest(args) ?? fromShowArgs(args);
  if (toolName !== "show_workflow") return null;
  const workflowId = String(args.workflow_id || "").trim();
  if (!workflowId) return null;
  const nodes = Array.isArray(args.node_ids) ? args.node_ids.map(String).filter(Boolean) : [];
  const group = String(args.group_id || "").trim();
  const target = group && !nodes.length ? `workflows.group.${group}` : nodes.map((id) => `workflows.node.${id}`);
  if (Array.isArray(target) && !target.length) return null;
  const note = String(args.note || "").trim();
  return parseShowMeRequest({
    target,
    workflow_id: workflowId,
    title: String(args.title || "").trim() || note || "In this workflow",
    body: String(args.body || "").trim() || (args.title ? note : ""),
  });
}

/** Play it again from the chat (the window you pressed it in). */
export async function replayShowMe(request: ShowMeRequest): Promise<string> {
  if (request.windowSpotlight) {
    const replay = getApi()?.window_spotlight_replay;
    if (!replay) return "Show me needs the desktop app";
    try {
      const out = await replay(request.windowSpotlight);
      return out?.error ? String(out.error) : "";
    } catch (err) {
      return err instanceof Error ? err.message : "Couldn't show it";
    }
  }
  const out = await playShowMe(request);
  if (out.error) return out.error;
  return out.missing ? "Can't find it on screen right now" : "";
}

export function ShowMeBody({ toolName, args, resultText, isError, showResult }: ToolCardBodyProps) {
  const request = useMemo(() => showMeRequestFromTool(toolName, args), [toolName, args]);
  const [note, setNote] = useState("");
  const missing = useMemo(() => {
    try {
      return !!(JSON.parse(resultText) as { missing?: boolean }).missing;
    } catch {
      return false;
    }
  }, [resultText]);

  const play = async (e?: MouseEvent | KeyboardEvent) => {
    e?.stopPropagation();
    if (!request) return;
    setNote(await replayShowMe(request));
  };

  if (!request) return <p className="tool-card-showme-empty">Nothing to show on this card.</p>;
  return (
    <div className="tool-card-showme">
      <div className="tool-card-showme-copy">
        <strong className="tool-card-showme-title">{showMeLabel(request)}</strong>
        {request.body ? <span className="tool-card-showme-text">{request.body.length > 160 ? `${request.body.slice(0, 157)}…` : request.body}</span> : null}
      </div>
      <button type="button" className="tool-card-showme-button" onClick={(e) => void play(e)} title="Take me there and highlight it">
        <Icons.Sparkles />
        <span>Show me</span>
      </button>
      {note ? <span className="tool-card-showme-note">{note}</span> : null}
      {!note && showResult && missing ? <span className="tool-card-showme-note">It wasn't on screen when Ducky showed it; press Show me to try again.</span> : null}
      {showResult && isError ? <span className="tool-card-showme-note tool-card-showme-note--error">Couldn't show it</span> : null}
    </div>
  );
}
