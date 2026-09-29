/**
 * Open the Workflows tab — one host-wide workflow editor.
 *
 * Same singleton pattern as Ledger: the header, the Tools menu, chat references,
 * and `ducky_ui_navigate("workflows")` all reach ChatView's opener.
 */

let openWorkflowsTabFn: (() => void) | null = null;

export function registerOpenWorkflowsTab(fn: () => void): () => void {
  openWorkflowsTabFn = fn;
  return () => {
    if (openWorkflowsTabFn === fn) openWorkflowsTabFn = null;
  };
}

export function requestOpenWorkflowsTab(): void {
  openWorkflowsTabFn?.();
}
