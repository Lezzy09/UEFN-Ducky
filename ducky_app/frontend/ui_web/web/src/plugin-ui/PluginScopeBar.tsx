import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { getApi } from "../hooks/usePanelApi";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import type { PluginScopeChoice, PluginScopeStatus } from "../types/panel";
import {
  dropConfirm,
  kindTitle,
  LOCAL_ONLY_TEXT,
  lostText,
  notShared,
  resetConfirm,
  resetText,
  storageLine,
  switchConfirm,
  syncText,
  unavailableText,
  type HeldItem,
} from "./scopeBarText";

/** Sync now waits for its round's result; a round stuck longer than this frees the button. */
const SYNC_NOW_GIVE_UP_MS = 120_000;
/** Changes not shared that are listed before "Show all". */
const HELD_SHOWN = 3;

/** Help text (same words as the web). */
const DATA_AT_REST = "Plugin data on each PC is encrypted for the signed-in account.";

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

/**
 * Host-rendered bar above every plugin panel: whose data this is. The plugin can't
 * hide or restyle it. Renders nothing while the account has no shared spaces to offer
 * (normal members see no change).
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
  const [allHeld, setAllHeld] = useState(false);
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
    return subscribePanelPush((event) => {
      if (event.type === "plugin_scope_changed") {
        if (event.synced) setSyncing(false);
        // A sync round with no changes for this plugin only refreshes the bar.
        const plugins = event.plugins ?? [];
        void refresh(plugins.includes(pluginId) || (!event.synced && plugins.length === 0));
      } else if (event.type === "duckyos_account_changed") {
        void refresh();
      }
    });
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
  const storage = shared ? storageLine(status.usage) : null;
  const state = status.state || "";
  const waiting = shared && state === "waiting";
  const locked = state === "locked";
  const lost = shared && state === "lost";
  const unavailable = shared && state === "unavailable";
  const reset = shared && state === "reset";
  // While reset, Retry and Drop wait: Upload or Clear my copy decides for the whole copy.
  const canRetry = Boolean(api?.plugin_scope_retry) && !reset;
  const canDrop = Boolean(api?.plugin_scope_drop) && !reset;
  const canSettle = Boolean(api?.space_reset_settle);
  const held = shared && !lost ? notShared(status) : { count: 0, items: [] };
  const heldShown = allHeld ? held.items : held.items.slice(0, HELD_SHOWN);
  const fixable = held.items.filter((item) => item.fixable).length;

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

  /** Send refused or blocked changes again (all of them without a key), then sync. */
  const retry = async (key?: string) => {
    // No key at all for "every one" (the bridge would send null for undefined).
    const run = async () => (key ? getApi()?.plugin_scope_retry?.(pluginId, key) : getApi()?.plugin_scope_retry?.(pluginId));
    if (await act(run)) void syncNow();
  };

  const drop = async (item: HeldItem) => {
    const ok = await confirm({ ...dropConfirm(scope.label, item.key), confirmLabel: "Drop my change", danger: true });
    if (ok !== true) return;
    await act(async () => getApi()?.plugin_scope_drop?.(pluginId, item.kind, item.key), true);
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

  const variant = shared ? (scope.readOnly && !waiting && !locked ? "paused" : "shared") : "personal";
  const paused = status.pausedText || `${scope.label} is paused. Read-only.`;
  // Shown in the phrase already: an unavailable copy's reason, and why nothing syncs.
  const errorInPhrase = state === "offline" || state === "unavailable" || state === "no_provider";
  return (
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
      {locked ? (
        <span className="plugin-scope-bar__text">
          Waiting for your account&apos;s data key. Read-only until you&apos;re back online.
        </span>
      ) : waiting ? (
        <span className="plugin-scope-bar__text">Waiting for {kind} data. Read-only until it arrives.</span>
      ) : lost ? (
        <span className="plugin-scope-bar__text">{lostText(scope.label, status.deleteAt)}</span>
      ) : unavailable ? (
        <span className="plugin-scope-bar__text">{unavailableText(scope.label, status.error)}</span>
      ) : reset ? (
        <>
          <span className="plugin-scope-bar__text">{resetText(scope.label, kind, canSettle)}</span>
          {canSettle ? (
            <>
              <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void settle("upload")}>
                Upload my copy
              </button>
              <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void settle("clear")}>
                Clear my copy
              </button>
            </>
          ) : null}
        </>
      ) : shared && scope.readOnly ? (
        <>
          <span className="plugin-scope-bar__text">{paused}</span>
          {status.pausedAction ? (
            <button
              type="button"
              className="plugin-scope-bar__link"
              onClick={() => void getApi()?.duckyos_open_site?.(status.pausedAction?.path || "/")}
            >
              {status.pausedAction.label}
            </button>
          ) : null}
        </>
      ) : (
        <>
          {status.email ? <span className="plugin-scope-bar__text">signed in as {status.email}</span> : null}
          {shared ? (
            <>
              {status.members ? (
                <span className="plugin-scope-bar__text">
                  shared with {status.members} member{status.members === 1 ? "" : "s"}
                </span>
              ) : null}
              <span className="plugin-scope-bar__text">{syncText(status, now)}</span>
              {storage ? (
                <span className={`plugin-scope-bar__storage plugin-scope-bar__storage--${storage.level}`}>
                  <progress
                    className="plugin-scope-bar__meter"
                    value={storage.pct}
                    max={100}
                    aria-label="Storage used"
                  />
                  <span>{storage.text}</span>
                  {storage.note ? <strong>{storage.note}</strong> : null}
                </span>
              ) : null}
            </>
          ) : (
            <span className="plugin-scope-bar__text">only on this PC · {DATA_AT_REST}</span>
          )}
        </>
      )}
      {status.error && !errorInPhrase ? (
        <span className="plugin-scope-bar__text plugin-scope-bar__text--error">{status.error}</span>
      ) : null}
      {actionError && actionError !== status.error ? (
        <span className="plugin-scope-bar__text plugin-scope-bar__text--error">{actionError}</span>
      ) : null}
      {shared && !lost && !locked && !reset ? (
        <button
          type="button"
          className="plugin-scope-bar__link plugin-scope-bar__sync"
          onClick={() => void syncNow()}
          disabled={syncing}
          title={`Send this PC's changes to ${scope.label} and get everyone else's now`}
        >
          {syncing ? "Syncing…" : "Sync now"}
        </button>
      ) : null}
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
      {held.count ? (
        <div className="plugin-scope-bar__held">
          <span className="plugin-scope-bar__held-title">Not shared: {held.count}</span>
          {canRetry && fixable > 1 ? (
            <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void retry()}>
              Retry all
            </button>
          ) : null}
          <ul className="plugin-scope-bar__held-list">
            {heldShown.map((item) => (
              <li key={`${item.kind}:${item.key}`} className="plugin-scope-bar__held-item">
                <span>{item.text}</span>
                {item.fixable && canRetry ? (
                  <button
                    type="button"
                    className="plugin-scope-bar__link"
                    aria-label={`Retry ${item.key}`}
                    disabled={busy}
                    onClick={() => void retry(item.key)}
                  >
                    Retry
                  </button>
                ) : null}
                {item.fixable && canDrop ? (
                  <button
                    type="button"
                    className="plugin-scope-bar__link"
                    aria-label={`Drop my change to ${item.key}`}
                    disabled={busy}
                    onClick={() => void drop(item)}
                  >
                    Drop my change
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {held.items.length > HELD_SHOWN ? (
            <button
              type="button"
              className="plugin-scope-bar__link"
              aria-expanded={allHeld}
              onClick={() => setAllHeld(!allHeld)}
            >
              {allHeld ? "Show fewer" : `Show all ${held.items.length}`}
            </button>
          ) : null}
          {held.count > held.items.length ? (
            <span className="plugin-scope-bar__text">{held.count - held.items.length} more not listed</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
