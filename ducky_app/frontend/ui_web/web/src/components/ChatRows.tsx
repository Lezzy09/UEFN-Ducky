import { useMemo, type ComponentPropsWithoutRef, type Ref } from "react";
import { ChatPaneEmptyState } from "./ChatPaneEmptyState";
import { CtrlWheelZoomRoot } from "./CtrlWheelZoomRoot";
import { DuckyParadeOverlay } from "./DuckyParade";
import { VirtualChatMessageList, type VirtualChatMessageListHandle } from "./VirtualChatMessageList";
import { buildActivityLines, splitTurnMessages } from "../utils/agentActivity";
import { appendStreamRow, buildCommittedChatRows, coalesceActivityRows } from "../utils/chatMessageGroups";

type Messages = Parameters<typeof splitTurnMessages>[0];

/** The chat's rows: committed history plus the live turn, regrouped only when messages change. */
export function useChatRowModel({
  messages,
  agentRunning,
  activeRunId,
  streamBuffer,
  streamThinking,
}: {
  messages: Messages;
  agentRunning: boolean;
  activeRunId: Parameters<typeof buildCommittedChatRows>[3];
  streamBuffer: string;
  streamThinking: string;
}) {
  const { committed, turnMessages } = useMemo(
    () => splitTurnMessages(messages, agentRunning),
    [messages, agentRunning],
  );

  // Regroup history only when messages change — not on every text/thinking delta.
  const committedRows = useMemo(
    () => buildCommittedChatRows(committed, turnMessages, agentRunning, activeRunId),
    [committed, turnMessages, agentRunning, activeRunId],
  );

  const rows = useMemo(
    () =>
      agentRunning
        ? coalesceActivityRows(
            appendStreamRow(committedRows, streamBuffer, true, streamThinking),
          )
        : committedRows,
    [committedRows, streamBuffer, streamThinking, agentRunning],
  );

  // Only the most recent user message is editable/resendable (Cursor: edit mid-answer).
  const editableRowId = useMemo(() => {
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i];
      if (r.kind === "bubble" && r.role === "user") return r.id;
    }
    return null;
  }, [rows]);

  const hasInlineTurnContent =
    turnMessages.length > 0 || !!streamBuffer.trim() || !!streamThinking.trim();

  const activityLines = useMemo(
    () =>
      buildActivityLines(
        turnMessages,
        agentRunning ? streamBuffer : "",
        agentRunning ? streamThinking : "",
      ),
    [turnMessages, streamBuffer, streamThinking, agentRunning],
  );

  return { rows, editableRowId, hasInlineTurnContent, activityLines };
}

export type ChatRowsListProps = ComponentPropsWithoutRef<typeof VirtualChatMessageList>;

export interface ChatRowsProps {
  chatId: string;
  isFocus: boolean;
  isPopup: boolean;
  hydrated: boolean;
  loadError: string | null | undefined;
  messageCount: number;
  onRetry: () => void;
  isEmpty: boolean;
  /** An empty chat still shows the list when a question or command card waits in it. */
  showEmptyState: boolean;
  emptyState: ComponentPropsWithoutRef<typeof ChatPaneEmptyState>;
  onZoomChange: (zoom: number) => void;
  listRef: Ref<VirtualChatMessageListHandle>;
  list: ChatRowsListProps;
}

/** The message area: Loading, a load error, the empty state, or the message list. */
export function ChatRows({
  chatId,
  isFocus,
  isPopup,
  hydrated,
  loadError,
  messageCount,
  onRetry,
  isEmpty,
  showEmptyState,
  emptyState,
  onZoomChange,
  listRef,
  list,
}: ChatRowsProps) {
  return (
    <div
      className={`selectable-text chat-pane-content${isFocus ? " chat-pane-content--focus" : ""}${isPopup ? " chat-pane-content--popup" : ""}`}
    >
      <CtrlWheelZoomRoot
        className={`chat-pane-inner${isEmpty || !hydrated ? " chat-pane-inner--empty" : ""}`}
        storageKey={`uefn-panel-chat-zoom:${chatId}`}
        onZoomChange={onZoomChange}
      >
        {!hydrated ? (
          <DuckyParadeOverlay label="Loading" />
        ) : loadError && messageCount === 0 ? (
          <div className="chat-pane-load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="settings-btn general-tab-btn-primary" onClick={onRetry}>
              Retry
            </button>
          </div>
        ) : showEmptyState ? (
          <ChatPaneEmptyState {...emptyState} />
        ) : (
          <VirtualChatMessageList ref={listRef} {...list} />
        )}
      </CtrlWheelZoomRoot>
    </div>
  );
}
