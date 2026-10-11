import { memo, useState, type ComponentType } from "react";
import { Icons } from "../icons/Icons";
import { requestOpenChatTab } from "../navigation/openChatReference";
import {
  automatedPromptText,
  codingAgentName,
  type AutomatedPart,
  type AutomatedPartKind,
  type AutomatedPrompt,
} from "../utils/automatedPrompt";
import { ChatRefText } from "./ChatRefText";
import { InlineStopButton } from "./InlineStopButton";
import { PromptCopyButton } from "./PromptCopyButton";

const PART_ICON: Record<AutomatedPartKind, ComponentType> = {
  message: Icons.Users,
  notice: Icons.AlertTriangle,
  plan: Icons.Plan,
  keeper: Icons.Clock,
};

/** Collapsed, a turn shows at most this many one-line rows (one row on a phone). */
const COLLAPSED_ROWS = 3;

function AutomatedPartView({
  part,
  compact,
  extra,
  more = 0,
}: {
  part: AutomatedPart;
  /** One line: who it is from, then the start of the text. */
  compact: boolean;
  /** Not the first row: a phone hides it while collapsed. */
  extra: boolean;
  /** Rows after this one, counted for the phone's single row. */
  more?: number;
}) {
  const Icon = PART_ICON[part.kind];
  const agent = codingAgentName(part.agent);

  return (
    <div className={`message-bubble-automated-part is-${part.kind}${compact ? " is-compact" : ""}${extra ? " is-extra" : ""}`}>
      <div className="message-bubble-automated-head">
        <span className="message-bubble-automated-icon" aria-hidden>
          <Icon />
        </span>
        {part.kind === "message" ? <span className="message-bubble-automated-label">From</span> : null}
        {part.fromConvId ? (
          <button
            type="button"
            className="message-bubble-automated-from"
            title={`Open ${part.from}`}
            onClick={(event) => {
              event.stopPropagation();
              requestOpenChatTab(part.fromConvId!, part.from);
            }}
          >
            {part.from}
          </button>
        ) : (
          <span className="message-bubble-automated-from is-static">{part.from}</span>
        )}
        {agent ? <span className="message-bubble-automated-agent">{agent}</span> : null}
        <span className="message-bubble-automated-tag">{part.tag}</span>
      </div>
      {part.body ? (
        <div className="message-bubble-automated-body">
          <ChatRefText text={part.body} />
        </div>
      ) : null}
      {more > 0 ? (
        <span className="message-bubble-automated-count" title={`${more} more`}>
          +{more}
        </span>
      ) : null}
    </div>
  );
}

/** A turn another agent or Ducky started in this chat: who sent it, never "you", never editable. */
export const AutomatedPromptMessage = memo(function AutomatedPromptMessage({
  prompt,
  onStop,
}: {
  prompt: AutomatedPrompt;
  /** Stop the live run this message started (the latest row only). */
  onStop?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const first = prompt.parts[0];
  const total = prompt.parts.length;
  const shownCount = expanded ? total : total > COLLAPSED_ROWS ? COLLAPSED_ROWS - 1 : total;
  const hidden = prompt.parts.slice(shownCount);
  const copy = automatedPromptText(prompt);
  const toggle = () => setExpanded((v) => !v);
  return (
    <div className="message-bubble-user-wrap">
      <div className="message-bubble-user-row">
        <div
          className={`message-bubble-user-content message-bubble-automated is-${first?.kind || "message"}${expanded ? " is-expanded" : ""}`}
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          aria-label={`${first?.tag || "Message"} from ${first?.from || "another agent"}, not from you`}
          title={expanded ? "Collapse" : "Expand"}
          onClick={(event) => {
            if ((event.target as HTMLElement).closest?.(".chat-ref-chip, .message-bubble-automated-from")) return;
            toggle();
          }}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return;
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggle();
            }
          }}
        >
          {onStop || copy ? (
            <div className="message-bubble-user-actions">
              {onStop ? <InlineStopButton onClick={onStop} /> : null}
              {copy ? <PromptCopyButton text={copy} /> : null}
            </div>
          ) : null}
          {expanded && prompt.heading ? <div className="message-bubble-automated-heading">{prompt.heading}</div> : null}
          {prompt.parts.slice(0, shownCount).map((part, index) => (
            <AutomatedPartView
              key={`${index}-${part.fromConvId || part.from}`}
              part={part}
              compact={!expanded}
              extra={index > 0}
              more={!expanded && index === 0 ? total - 1 : 0}
            />
          ))}
          {hidden.length ? (
            <div className="message-bubble-automated-more is-extra">
              +{hidden.length} more from {[...new Set(hidden.map((part) => part.from))].join(", ")}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
});
