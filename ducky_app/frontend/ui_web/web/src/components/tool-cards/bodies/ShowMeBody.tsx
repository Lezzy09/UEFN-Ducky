import { useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Icons } from "../../../icons/Icons";
import { parseShowMeRequest, playShowMe, type ShowMeRequest } from "../../../showme/ShowMeService";
import type { ToolCardBodyProps } from "../toolCardTypes";

/** The Show me a tool call stands for: ducky_ui_show's own arguments, or show_workflow's nodes. */
export function showMeRequestFromTool(toolName: string, args: Record<string, unknown>): ShowMeRequest | null {
  if (toolName === "ducky_ui_show") return parseShowMeRequest(args);
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
        <strong className="tool-card-showme-title">{request.title}</strong>
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
