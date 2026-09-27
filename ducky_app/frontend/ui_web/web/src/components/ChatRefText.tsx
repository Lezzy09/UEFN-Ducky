import type { ReactNode } from "react";
import { findChatRefTokens } from "./chatReferences";
import { requestOpenChatReference } from "../navigation/openChatReference";
import { ChatRefChip } from "./ChatRefChip";

/** User-bubble text stays plain. Stored mentions render as icon chips. */
export function ChatRefText({ text }: { text: string }) {
  const tokens = findChatRefTokens(text);
  if (!tokens.length) return <>{text}</>;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  tokens.forEach((token, index) => {
    if (token.start > cursor) nodes.push(text.slice(cursor, token.start));
    nodes.push(
      <ChatRefChip
        key={`${token.start}-${index}`}
        href={token.href}
        label={token.label}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          requestOpenChatReference(token.href, token.label);
        }}
      />,
    );
    cursor = token.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return <>{nodes}</>;
}
