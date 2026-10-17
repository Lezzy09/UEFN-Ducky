import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { getApi } from "../hooks/usePanelApi";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import type { PluginScopeChoice, PluginScopeStatus } from "../types/panel";
import { PluginScopeDrawer } from "./PluginScopeDrawer";
import { installScopeAlerts, onRefusedWrite, rememberPluginLabel, type RefusedWrite } from "./scopeAlerts";
import {
  DATA_AT_REST,
  kindTitle,
  LOCAL_ONLY_TEXT,
  locksText,
  notShared,
  peopleRows,
  peopleText,
  resetConfirm,
  statusPhrase,
  storageLine,
  switchConfirm,
} from "./scopeBarText";

/** Sync now waits for its round's result; a round stuck longer than this frees the button. */
const SYNC_NOW_GIVE_UP_MS = 120_000;

type Props = {
  pluginId: string;
  /** The plugin's data or scope changed: the pane tells the iframe to re-read. */
  onScopeChanged: (status: PluginScopeStatus) => void;
  /** False while the tab is kept but hidden: no sync for a panel nobody sees. */
  active?: boolean;
};

type ActionResult = { ok?: boolean; error?: string } | undefined;

/** Whose data: account + scope. Any change means the plugin must re-read. */
const scopeKey = (s: PluginScopeStatus | null) =>
  s ? `${s.email}:${s.scope?.kind}:${s.scope?.spaceId}:${s.scope?.readOnly}` : "";

/** Phrases that already carry `status.error`, or say what it says (a reset, lost access). */
const ERROR_IN_PHRASE = new Set(["not_synced", "no_provider", "unavailable", "reset", "lost"]);

/** The drawer's open state, per plugin and per viewer (a convenience: storage may be off). */
const drawerKey = (pluginId: string) => `ducky.pluginScopeDrawer.${pluginId}`;
function readDrawerOpen(pluginId: string): boolean {
  try {
    return localStorage.getItem(drawerKey(pluginId)) === "1";
  } catch {
    return false;
  }
}
function writeDrawerOpen(pluginId: string, open: boolean): void {
  try {
    if (open) localStorage.setItem(drawerKey(pluginId), "1");
    else localStorage.removeItem(drawerKey(pluginId));
  } catch {
    /* storage off: the drawer just starts closed */
  }
}

/**
 * Host-rendered line above every plugin panel: whose data this is, one status phrase, who
 * else is here and what is locked, Sync now (Push and Pull in Manual mode) and Details, which
 * opens the drawer under it. The plugin can't hide or restyle it. Renders nothing while the
 * account has no shared spaces to offer (normal members see no change).
 */
export function PluginScopeBar({ pluginId, onScopeChanged, active = true }: Props) {
  const { confirm } = useConfirmModal();
  const [status, setStatus] = useState<PluginScopeStatus | null>(null);
  const [menu, setMenu] = useState<PluginScopeChoice[] | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [syncing, setSyncing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(() => readDrawerOpen(pluginId));
  const [refused, setRefused] = useState<{ write: RefusedWrite; text: string; asked?: boolean } | null>(null);
  const notify = useRef(onScopeChanged);
  notify.current = onScopeChanged;
  const last = useRef<PluginScopeStatus | null>(null);

  /** Re-read the bar; tell the iframe when the scope moved or its data changed. */
  const refresh = useCallback(async (dataChanged = false) => {
    const api = getApi();
    if (!api?.plugin_scope_status) return;
    try {
      const next = await api.plugin_scope_status(pluginId);
      const moved = last.current !== null && scopeKey(next) !== scopeKey(last.current);
      last.current = next;
      rememberPluginLabel(pluginId, next.pluginLabel);
      setStatus(next);
      setNow(Date.now());
      if (moved || dataChanged) notify.current(next);
    } catch {
      /* keep the last bar */
    }
  }, [pluginId]);

  useEffect(() => {
    void refresh();
    installPanelPushBus();
    installScopeAlerts(); // refused writes, asks and lost locks are told app-wide (the app installs it too)
    const stopPush = subscribePanelPush((event) => {
      if (event.type === "plugin_scope_changed") {
        if (event.synced) setSyncing(false);
        // A sync round with no changes for this plugin only refreshes the bar.
        const plugins = event.plugins ?? [];
        void refresh(plugins.includes(pluginId) || (!event.synced && plugins.length === 0));
      } else if (event.type === "duckyos_account_changed") {
        void refresh();
      }
    });
    const stopRefused = onRefusedWrite((write, text) => {
      if (write.pluginId === pluginId) setRefused({ write, text });
    });
    return () => {
      stopPush();
      stopRefused();
    };
  }, [refresh, pluginId]);

  // Core's scheduler syncs shared copies in the background; the bar only asks for a
  // round when the panel opens and when the window gets focus (the provider rate-limits).
  const spaceId = status?.visible && status.scope?.kind === "shared" ? status.scope.spaceId : "";
  useEffect(() => {
    if (!spaceId || !active) return;
    const sync = () => {
      setNow(Date.now());
      void getApi()?.plugin_scope_sync?.(pluginId, false);
    };
    sync();
    window.addEventListener("focus", sync);
    return () => window.removeEventListener("focus", sync);
  }, [spaceId, pluginId, active]);

  useEffect(() => {
    if (!syncing) return;
    const giveUp = window.setTimeout(() => setSyncing(false), SYNC_NOW_GIVE_UP_MS);
    return () => window.clearTimeout(giveUp);
  }, [syncing]);

  // "retry in 40 s" counts down while the panel is on screen.
  const nextTry = status?.nextTry ?? 0;
  useEffect(() => {
    if (!active || !nextTry || nextTry * 1000 <= Date.now()) return;
    const tick = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= nextTry * 1000) window.clearInterval(tick);
    }, 1000);
    return () => window.clearInterval(tick);
  }, [nextTry, active]);

  /** A full round now (sends this PC's changes, brings everyone else's), past the minute cap. */
  const syncNow = async () => {
    setActionError("");
    setSyncing(true);
    try {
      const res = await getApi()?.plugin_scope_sync?.(pluginId, true);
      if (res?.ok && res.started) return;
      setSyncing(false);
      if (res?.ok === false && res.error) setActionError(res.error);
    } catch (err) {
      setSyncing(false);
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  /** One bar action; its error stays on the bar until the next one. True when it worked. */
  const act = async (run: () => Promise<ActionResult>, dataChanged = false): Promise<boolean> => {
    setActionError("");
    setBusy(true);
    try {
      const res = await run();
      if (res?.ok === false) {
        setActionError(res.error || "That didn't work. Try again.");
        return false;
      }
      await refresh(dataChanged);
      return true;
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const toggleDrawer = () => {
    const open = !drawerOpen;
    setDrawerOpen(open);
    writeDrawerOpen(pluginId, open);
  };

  if (!status?.visible || !status.scope) return null;
  const scope = status.scope;
  const shared = scope.kind === "shared";

  if (!shared && status.shareable === false) {
    // Nothing of this plugin goes through the host data service: no space to offer.
    return (
      <div className="plugin-scope-bar plugin-scope-bar--personal" role="status" aria-live="polite" aria-label="Plugin data: local">
        <span className="plugin-scope-bar__badge plugin-scope-bar__badge--local">Local</span>
        <span className="plugin-scope-bar__text">{LOCAL_ONLY_TEXT}</span>
      </div>
    );
  }

  const api = getApi();
  const kind = (status.kindLabel || "space").toLowerCase();
  const plugin = status.pluginLabel || pluginId;
  const current = shared ? scope.spaceId : "personal";
  const state = status.state || "";
  const waiting = shared && state === "waiting";
  const keyLocked = state === "locked";
  const lost = shared && state === "lost";
  const reset = shared && state === "reset";
  const canSettle = Boolean(api?.space_reset_settle);
  const phrase = statusPhrase(status, now);
  const people = shared ? peopleText(peopleRows(status.people, pluginId)) : "";
  const locks = shared ? locksText(status.locks) : "";
  const storage = shared ? storageLine(status.usage) : null;
  const manual = shared && status.mode === "manual" && Boolean(api?.plugin_scope_push || api?.plugin_scope_pull);
  const canSync = shared && !lost && !keyLocked && !reset;

  const toggleMenu = async () => {
    if (menuOpen) {
      setMenuOpen(false);
      return;
    }
    setMenuOpen(true);
    setMenu(null);
    if (!status.canChange) return;
    const res = await getApi()?.plugin_scope_choices?.();
    setMenu(res?.choices ?? []);
  };

  const choose = async (choice: PluginScopeChoice) => {
    setMenuOpen(false);
    if (choice.id === current) return;
    // Counts as of now: the background scheduler may have sent some since the last refresh.
    if (shared) await refresh();
    const before = last.current ?? status;
    const from = shared ? { label: scope.label, pending: before.pending ?? 0, held: notShared(before).count } : undefined;
    const ok = await confirm({ ...switchConfirm(plugin, choice, from), confirmLabel: "Switch" });
    if (ok !== true) return;
    setActionError("");
    const next = await getApi()?.plugin_scope_set?.(pluginId, choice.id);
    if (next?.ok === false && next.error) {
      setActionError(next.error);
      return;
    }
    await refresh();
  };

  /** Upload my copy / Clear my copy: for this PC's whole copy of the space, which the
   * confirm names. The host starts the round. */
  const settle = async (action: "upload" | "clear") => {
    const ask = resetConfirm(action, scope.label, status.resetContents ?? []);
    const ok = await confirm(action === "upload"
      ? { ...ask, confirmLabel: "Upload my copy" }
      : { ...ask, confirmLabel: "Yes, clear it", danger: true });
    if (ok !== true) return;
    await act(async () => getApi()?.space_reset_settle?.(scope.spaceId, action), action === "clear");
  };

  /** Update now / Pull: bring everyone's changes in now. */
  const pull = () =>
    act(async () => (api?.plugin_scope_pull ? api.plugin_scope_pull(pluginId) : api?.plugin_scope_sync?.(pluginId, true)), true);
  const push = () => act(async () => api?.plugin_scope_push?.(pluginId));

  const askRelease = async () => {
    const write = refused?.write;
    if (!write?.unit) return;
    if (await act(async () => api?.plugin_scope_ask?.(pluginId, write.unit as string))) {
      setRefused({ write, text: `Asked ${write.holder || "them"} to release ${write.name || write.unit}.`, asked: true });
    }
  };

  const variant = shared ? (scope.readOnly && !waiting && !keyLocked ? "paused" : "shared") : "personal";
  const storageNote = storage && storage.level !== "ok" ? (storage.level === "full" ? storage.note : `Storage ${storage.note}`) : "";
  const drawerId = `plugin-scope-drawer-${pluginId}`;
  return (
    <div className="plugin-scope">
      <div
        className={`plugin-scope-bar plugin-scope-bar--${variant}`}
        role="status"
        aria-live="polite"
        aria-label={shared ? `Plugin data: ${kind} ${scope.label}` : "Plugin data: local"}
        title={DATA_AT_REST}
      >
        <span
          className={`plugin-scope-bar__badge plugin-scope-bar__badge--${shared ? "shared" : "local"}`}
          title={shared ? `${kindTitle(kind)} data: ${scope.label}` : "Local data: only on this PC"}
        >
          {shared ? scope.label : "Local"}
        </span>
        <span className="plugin-scope-bar__change">
          <button
            type="button"
            className="plugin-scope-bar__link"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => void toggleMenu()}
          >
            Change ▾
          </button>
          {menuOpen ? (
            <span className="plugin-scope-bar__menu" role="menu">
              {!status.canChange ? (
                <span className="plugin-scope-bar__menu-note">Open a project to choose whose data it shows.</span>
              ) : menu === null ? (
                <span className="plugin-scope-bar__menu-note">Loading…</span>
              ) : (
                menu.map((choice) => (
                  <button
                    key={choice.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={choice.id === current}
                    className="plugin-scope-bar__menu-item"
                    onClick={() => void choose(choice)}
                  >
                    {choice.kind === "shared" ? `${kindTitle(kind)} · ${choice.label}` : "Local"}
                  </button>
                ))
              )}
            </span>
          ) : null}
        </span>
        <span className={`plugin-scope-bar__text plugin-scope-bar__phrase${phrase.tone ? ` plugin-scope-bar__text--${phrase.tone}` : ""}`}>
          {phrase.text}
        </span>
        {phrase.action === "update" ? (
          <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void pull()}>
            Update now
          </button>
        ) : null}
        {reset && canSettle ? (
          <>
            <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void settle("upload")}>
              Upload my copy
            </button>
            <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void settle("clear")}>
              Clear my copy
            </button>
          </>
        ) : null}
        {phrase.key === "paused" && status.pausedAction ? (
          <button
            type="button"
            className="plugin-scope-bar__link"
            onClick={() => void getApi()?.duckyos_open_site?.(status.pausedAction?.path || "/")}
          >
            {status.pausedAction.label}
          </button>
        ) : null}
        {people ? <span className="plugin-scope-bar__text">{people}</span> : null}
        {locks ? <span className="plugin-scope-bar__text">{locks}</span> : null}
        {storageNote ? <span className="plugin-scope-bar__text plugin-scope-bar__text--warn">{storageNote}</span> : null}
        {status.error && !ERROR_IN_PHRASE.has(phrase.key) ? (
          <span className="plugin-scope-bar__text plugin-scope-bar__text--error">{status.error}</span>
        ) : null}
        {refused ? (
          <>
            <span className={`plugin-scope-bar__text${refused.asked ? "" : " plugin-scope-bar__text--error"}`}>{refused.text}</span>
            {!refused.asked && refused.write.unit && refused.write.holder && api?.plugin_scope_ask ? (
              <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void askRelease()}>
                Ask to release
              </button>
            ) : null}
            <button type="button" className="plugin-scope-bar__link" onClick={() => setRefused(null)}>
              Dismiss
            </button>
          </>
        ) : null}
        {actionError && actionError !== status.error ? (
          <span className="plugin-scope-bar__text plugin-scope-bar__text--error">{actionError}</span>
        ) : null}
        <span className="plugin-scope-bar__actions">
          {canSync && manual ? (
            <>
              {api?.plugin_scope_push ? (
                <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void push()}
                  title={`Send this PC's changes to ${scope.label} now`}>
                  Push
                </button>
              ) : null}
              {api?.plugin_scope_pull ? (
                <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void pull()}
                  title={`Get everyone else's changes from ${scope.label} now`}>
                  Pull
                </button>
              ) : null}
            </>
          ) : canSync ? (
            <button
              type="button"
              className="plugin-scope-bar__link"
              onClick={() => void syncNow()}
              disabled={syncing}
              title={`Send this PC's changes to ${scope.label} and get everyone else's now`}
            >
              {syncing ? "Syncing…" : "Sync now"}
            </button>
          ) : null}
          {shared ? (
            <button
              type="button"
              className="plugin-scope-bar__link"
              aria-expanded={drawerOpen}
              aria-controls={drawerId}
              onClick={toggleDrawer}
            >
              Details ▾
            </button>
          ) : null}
        </span>
      </div>
      {shared && drawerOpen ? (
        <PluginScopeDrawer id={drawerId} pluginId={pluginId} status={status} onChanged={(changed) => refresh(changed)} />
      ) : null}
    </div>
  );
}
