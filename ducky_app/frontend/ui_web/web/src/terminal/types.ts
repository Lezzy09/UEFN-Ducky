export type TerminalShell = "bash" | "powershell";

export interface TerminalSessionDto {
  session_id: string;
  shell: TerminalShell;
  cwd: string;
  title: string;
  ws_url: string;
  /** Title of the ducky (chat) that opened it; empty for the person's own. */
  owner?: string;
  busy?: boolean;
  alive?: boolean;
  tab_id?: string;
}

export interface PendingTerminalCommand {
  request_id: string;
  session_id: string;
  command: string;
  shell?: string;
  cwd?: string;
  conv_id?: string;
  source?: string;
  /** What "Always allow … in this chat" names; empty = not offered (pushes, deletes, chains). */
  rule_label?: string;
  /** Unix seconds when the agent asked. */
  created_at?: number;
  /** A team member's card also shows in its lead's chat (the chat that started its run). */
  lead_conv_id?: string;
  /** The member that asked, named on the lead's copy of the card. */
  asked_by?: string;
}

/** once / always (this command in this chat) / all (everything in this chat) / deny. */
export type TerminalApprovalChoice = "once" | "always" | "all" | "deny";

export interface TerminalSpawnResult {
  ok: boolean;
  session_id?: string;
  shell?: TerminalShell;
  cwd?: string;
  title?: string;
  ws_url?: string;
  tab_id?: string;
  shell_fallback?: boolean;
  error?: string;
}

export const DEFAULT_TERMINAL_SHELL: TerminalShell =
  typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent) ? "powershell" : "bash";

export function terminalTabLabel(shell: TerminalShell, title?: string): string {
  const base = title?.trim() || shell;
  return base.length > 24 ? `${base.slice(0, 22)}…` : base;
}
