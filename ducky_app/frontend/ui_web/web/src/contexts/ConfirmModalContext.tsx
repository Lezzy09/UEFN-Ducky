import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { Modal, ModalActions } from "../components/Modal";

export interface ConfirmOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  /** Second action, beside confirm. Resolves the promise to "extra". */
  extraLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

export type ConfirmResult = boolean | "extra";

export interface AlertOptions {
  title?: string;
  message: string;
  okLabel?: string;
}

type DialogState =
  | { type: "confirm"; options: ConfirmOptions; resolve: (result: ConfirmResult) => void }
  | { type: "alert"; options: AlertOptions; resolve: () => void };

interface ConfirmModalContextValue {
  confirm: (options: ConfirmOptions | string) => Promise<ConfirmResult>;
  alert: (options: AlertOptions | string) => Promise<void>;
}

const ConfirmModalContext = createContext<ConfirmModalContextValue | null>(null);

function normalizeConfirm(options: ConfirmOptions | string): ConfirmOptions {
  return typeof options === "string" ? { message: options } : options;
}

function normalizeAlert(options: AlertOptions | string): AlertOptions {
  return typeof options === "string" ? { message: options } : options;
}

function confirmShortcutKey(label: string): string | null {
  const match = label.trim().match(/[a-z0-9]/i);
  return match ? match[0].toLowerCase() : null;
}

// The mounted provider's dialogs, reachable from code that runs outside React
// (the plugin-panel bridge): a plugin's "are you sure?" opens Ducky's own modal.
let mountedDialogs: ConfirmModalContextValue | null = null;

export function confirmFromHost(options: ConfirmOptions | string): Promise<ConfirmResult> {
  if (!mountedDialogs) return Promise.reject(new Error("confirm dialog is not mounted"));
  return mountedDialogs.confirm(options);
}

export function alertFromHost(options: AlertOptions | string): Promise<void> {
  if (!mountedDialogs) return Promise.reject(new Error("alert dialog is not mounted"));
  return mountedDialogs.alert(options);
}

export function ConfirmModalProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<DialogState | null>(null);

  const confirm = useCallback((options: ConfirmOptions | string): Promise<ConfirmResult> => {
    const opts = normalizeConfirm(options);
    return new Promise((resolve) => {
      setDialog({ type: "confirm", options: opts, resolve });
    });
  }, []);

  const alert = useCallback((options: AlertOptions | string): Promise<void> => {
    const opts = normalizeAlert(options);
    return new Promise((resolve) => {
      setDialog({ type: "alert", options: opts, resolve });
    });
  }, []);

  useEffect(() => {
    mountedDialogs = { confirm, alert };
    return () => {
      if (mountedDialogs && mountedDialogs.confirm === confirm) mountedDialogs = null;
    };
  }, [confirm, alert]);

  const dismissConfirm = (result: ConfirmResult) => {
    if (dialog?.type !== "confirm") return;
    dialog.resolve(result);
    setDialog(null);
  };

  const dismissAlert = () => {
    if (dialog?.type !== "alert") return;
    dialog.resolve();
    setDialog(null);
  };

  const title =
    dialog?.type === "confirm"
      ? (dialog.options.title ?? "Confirm")
      : dialog?.type === "alert"
        ? (dialog.options.title ?? "Notice")
        : "";

  const message = dialog?.options.message ?? "";
  const confirmLabel = dialog?.type === "confirm" ? (dialog.options.confirmLabel ?? "OK") : "";
  const confirmKey = dialog?.type === "confirm" ? confirmShortcutKey(confirmLabel) : null;
  const extraLabel = dialog?.type === "confirm" ? (dialog.options.extraLabel ?? "") : "";
  // The second action gets its own letter too (Archive (A) · Delete (D)), unless it clashes.
  const extraKeyRaw = extraLabel ? confirmShortcutKey(extraLabel) : null;
  const extraKey = extraKeyRaw && extraKeyRaw !== "c" && extraKeyRaw !== confirmKey ? extraKeyRaw : null;

  useEffect(() => {
    if (!dialog || dialog.type !== "confirm" || (!confirmKey && !extraKey)) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target;
      if (
        target instanceof HTMLElement &&
        target.closest('input, textarea, select, [contenteditable="true"]')
      ) {
        return;
      }

      const key = e.key.toLowerCase();
      if (key === "c") {
        e.preventDefault();
        dialog.resolve(false);
        setDialog(null);
      } else if (key === confirmKey) {
        e.preventDefault();
        dialog.resolve(true);
        setDialog(null);
      } else if (key === extraKey) {
        e.preventDefault();
        dialog.resolve("extra");
        setDialog(null);
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [dialog, confirmKey, extraKey]);

  return (
    <ConfirmModalContext.Provider value={{ confirm, alert }}>
      {children}
      {dialog ? (
        <Modal
          open
          onClose={() => (dialog.type === "confirm" ? dismissConfirm(false) : dismissAlert())}
          title={title}
          width={420}
          footer={
            dialog.type === "confirm" ? (
              <ModalActions
                cancelLabel={`${dialog.options.cancelLabel ?? "Cancel"} (C)`}
                extraLabel={extraKey ? `${extraLabel} (${extraKey.toUpperCase()})` : extraLabel}
                confirmLabel={
                  confirmKey
                    ? `${confirmLabel} (${confirmKey.toUpperCase()})`
                    : confirmLabel
                }
                danger={dialog.options.danger}
                onCancel={() => dismissConfirm(false)}
                onExtra={() => dismissConfirm("extra")}
                onConfirm={() => dismissConfirm(true)}
              />
            ) : (
              <ModalActions
                hideCancel
                confirmLabel={dialog.options.okLabel ?? "OK"}
                onCancel={dismissAlert}
                onConfirm={dismissAlert}
              />
            )
          }
        >
          <p className="confirm-modal-message">{message}</p>
        </Modal>
      ) : null}
    </ConfirmModalContext.Provider>
  );
}

export function useConfirmModal(): ConfirmModalContextValue {
  const ctx = useContext(ConfirmModalContext);
  if (!ctx) {
    throw new Error("useConfirmModal must be used within ConfirmModalProvider");
  }
  return ctx;
}
