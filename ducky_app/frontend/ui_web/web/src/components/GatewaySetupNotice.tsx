/**
 * First-run explainer plus the top-right gateway nag.
 * Hidden whenever any gateway plugin is already installed.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { onApiReady } from "../hooks/onApiReady";
import {
  beginStoreInstall,
  clearStoreJobLater,
  endStoreInstall,
  patchStoreJob,
} from "../hooks/storeInstallJobs";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import { requestOpenStore } from "../navigation/deepLinks";
import { ensurePopularPlugins } from "../walkthrough/starterLlmGateways";
import "./gateway-setup.css";

type Progress = {
  label: string;
  index: number;
  total: number;
  setup_phase?: string;
  detail?: string;
};

function reflectStoreProgress(
  slug: string,
  label: string,
  phase: string | undefined,
  detail: string | undefined,
): void {
  const base = { slug, name: label, label: `Downloading ${label}…` };
  if (phase === "installing") {
    beginStoreInstall(slug);
    patchStoreJob(slug, { ...base, phase: "working", step: "download" });
    return;
  }
  if (phase === "installed") {
    endStoreInstall(slug);
    clearStoreJobLater(slug, { ...base, label: `Installed ${label}`, phase: "done", step: "done" });
    return;
  }
  if (phase === "error") {
    endStoreInstall(slug);
    clearStoreJobLater(slug, {
      ...base,
      label: detail || `Couldn't install ${label}`,
      phase: "error",
      step: "done",
    });
    return;
  }
  if (phase === "skipped") {
    endStoreInstall(slug);
    patchStoreJob(slug, null);
  }
}

function progressLine(progress: Progress | null): string {
  if (!progress?.label) return "";
  if (progress.setup_phase === "error") {
    return progress.detail ? `Couldn't install ${progress.label}. ${progress.detail}` : `Couldn't install ${progress.label}.`;
  }
  if (progress.setup_phase === "installing") {
    return `Installing ${progress.label} (${progress.index} of ${progress.total})`;
  }
  if (progress.index && progress.total) {
    return `${progress.label} (${progress.index} of ${progress.total})`;
  }
  return "";
}

export function GatewaySetupNotice() {
  const [ready, setReady] = useState(false);
  const [pending, setPending] = useState(false);
  const [gatewayIds, setGatewayIds] = useState<string[]>([]);
  const [minimized, setMinimized] = useState(false);
  const [pill, setPill] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = () => {
    onApiReady((api) => {
      if (!api.starter_setup_status) return;
      void api.starter_setup_status().then((status) => {
        setGatewayIds(status?.gateway_ids || []);
        setPending(!!status?.pending_first_run);
        setReady(true);
      }).catch(() => {
        /* Stay hidden when status can't be read. */
      });
    });
  };

  useEffect(() => {
    installPanelPushBus();
    const stopReady = onApiReady((api) => {
      if (!api.starter_setup_status) return;
      void api.starter_setup_status().then((status) => {
        setGatewayIds(status?.gateway_ids || []);
        setPending(!!status?.pending_first_run);
        setReady(true);
      }).catch(() => {
        /* Stay hidden when status can't be read. */
      });
    });
    const stopPush = subscribePanelPush((event) => {
      if (event.type === "starter_plugins_progress") {
        const slug = event.slug || "";
        const label = event.label || slug;
        setProgress({
          label,
          index: event.index || 0,
          total: event.total || 0,
          setup_phase: event.setup_phase,
          detail: event.detail,
        });
        if (slug) reflectStoreProgress(slug, label, event.setup_phase, event.detail);
      }
      if (event.type === "uefn_plugins_changed" || event.type === "starter_plugins_progress") {
        refresh();
      }
    });
    return () => {
      stopReady();
      stopPush();
    };
  }, []);

  const run = (force: boolean) => {
    setBusy(true);
    setError("");
    setMinimized(true);
    requestOpenStore();
    void ensurePopularPlugins(force)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Download failed");
      })
      .finally(() => setBusy(false));
  };

  if (!ready || gatewayIds.length > 0) return null;

  const line = error || progressLine(progress);
  const showModal = pending && !minimized;

  if (showModal) {
    return createPortal(
      <div className="gateway-setup no-drag" role="dialog" aria-label="Set up UEFN Ducky">
        <section className="gateway-setup-modal">
          <header className="gateway-setup-head">
            <h2>Set up UEFN Ducky</h2>
            <button type="button" className="gateway-setup-min" onClick={() => setMinimized(true)}>
              Minimize
            </button>
          </header>
          <p>
            Ducky needs a model gateway and the UEFN editor plugins so chats, Verse, and the
            editor tools work out of the box. This download adds OpenAI, Anthropic, and Cursor,
            plus Verse, level design, materials, VFX, and the other UEFN editor tools.
          </p>
          <p className="gateway-setup-note">Add an API key afterward in Settings → LLMs.</p>
          {line ? <p className="gateway-setup-progress">{line}</p> : null}
          <button
            type="button"
            className="update-toast-btn update-toast-btn-primary gateway-setup-go"
            disabled={busy}
            onClick={() => run(false)}
          >
            {busy ? "Downloading…" : "Download most popular gateways and plugins"}
          </button>
        </section>
      </div>,
      document.body,
    );
  }

  if (pill) {
    return createPortal(
      <div className="gateway-setup gateway-setup--corner no-drag">
        <button type="button" className="gateway-setup-pill" onClick={() => setPill(false)}>
          Set up gateways
        </button>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <div className="gateway-setup gateway-setup--corner no-drag" role="status" aria-live="polite">
      <section className="gateway-setup-card">
        <header className="gateway-setup-head">
          <h2>Download a gateway</h2>
          <button type="button" className="gateway-setup-min" onClick={() => setPill(true)}>
            Minimize
          </button>
        </header>
        <p>
          Chats need at least one gateway plugin — OpenAI, Anthropic, or Cursor. This also
          installs the UEFN editor plugins. This stays here until a gateway is installed.
        </p>
        {line ? <p className="gateway-setup-progress">{line}</p> : null}
        <button
          type="button"
          className="update-toast-btn update-toast-btn-primary gateway-setup-go"
          disabled={busy}
          onClick={() => run(true)}
        >
          {busy ? "Downloading…" : "Download most popular gateways and plugins"}
        </button>
      </section>
    </div>,
    document.body,
  );
}
