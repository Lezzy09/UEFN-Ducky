import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { getApi } from "../hooks/usePanelApi";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import type {
  PanelApi,
  PluginFolderShareUnit,
  PluginScopeChoice,
  PluginScopeFirstShare,
  PluginScopeStatus,
} from "../types/panel";
import { FolderShareDialog } from "./FolderShareDialog";
import { PluginScopeDrawer } from "./PluginScopeDrawer";
import { PresenceAvatar } from "./PresenceAvatar";
import { installScopeAlerts, onRefusedWrite, rememberPluginLabel, type RefusedWrite } from "./scopeAlerts";
import {
  bindingText,
  DATA_AT_REST,
  folderRefusal,
  folderNote,
  hasFolders,
  hereText,
  kindTitle,
  liveText,
  locksText,
  notShared,
  othersHere,
  presence,
  resetConfirm,
  sharingText,
  statusPhrase,
  storageLine,
  switchConfirm,
} from "./scopeBarText";

/** Sync now waits for its round's result; a round stuck longer than this frees the button. */
const SYNC_NOW_GIVE_UP_MS = 120_000;
/** How often the bar reads a switch's progress ("Getting Alpha's files… 40%"). */
const BINDING_POLL_MS = 1000;
/** Pushes that land together (a round's, a lock's, another plugin's) make one status read. */
const REFRESH_SETTLE_MS = 400;
/** Teammates' changes reach the panel at most this often, merged into one note. */
const TELL_SETTLE_MS = 800;
/** "Up to date · 12 s ago" moves on by itself while the panel is on screen. */
const AGO_TICK_MS = 15_000;
/** People shown as avatars on the bar before "+N". */
const AVATARS_SHOWN = 4;

/** What the panel is told (bridge event `plugin_scope_changed`). `switched`: whose data it
 * shows changed (account, Local or a space): start over. `synced`: a sync brought new data
 * into the same copy: re-read `keys` (every key when absent) and keep what is open. */
export type ScopeChange = { reason: "switched" | "synced"; keys?: string[]; live?: boolean };

type Props = {
  pluginId: string;
  /** The panel is told its data moved or changed (see {@link ScopeChange}). */
  onScopeChanged: (status: PluginScopeStatus, change: ScopeChange) => void;
  /** False while the tab is kept but hidden: no sync and no status reads for a panel nobody sees. */
  active?: boolean;
  /** Live editing went on or off (the pane tells the page's pointer script). */
  onLiveState?: (on: boolean) => void;
};

/** Live, per plugin and per viewer: the bar goes live again on its own next time. */
const liveKey = (pluginId: string) => `ducky.pluginLive.${pluginId}`;
function readLiveChoice(pluginId: string): boolean {
  try {
    return localStorage.getItem(liveKey(pluginId)) === "1";
  } catch {
    return false;
  }
}
function writeLiveChoice(pluginId: string, on: boolean): void {
  try {
    if (on) localStorage.setItem(liveKey(pluginId), "1");
    else localStorage.removeItem(liveKey(pluginId));
  } catch {
    /* storage off: Go live again next time */
  }
}

/** Data that changed for this plugin and isn't told yet; `keys` null: unknown, re-read all. */
type Pending = { keys: Set<string> | null };

function mergePending(prev: Pending | null, keys: string[] | null): Pending {
  if (!prev) return { keys: keys ? new Set(keys) : null };
  if (!prev.keys || !keys) return { keys: null };
  for (const key of keys) prev.keys.add(key);
  return prev;
}

type ActionResult = { ok?: boolean; error?: string } | undefined;

/** Whose data: account + scope. Any change means the plugin must re-read. */
const scopeKey = (s: PluginScopeStatus | null) =>
  s ? `${s.email}:${s.scope?.kind}:${s.scope?.spaceId}:${s.scope?.readOnly}` : "";

/** Phrases that already carry `status.error`, or say what it says (a reset, lost access). */
const ERROR_IN_PHRASE = new Set(["not_synced", "no_provider", "unavailable", "reset", "lost"]);

/** A first share waiting for the person to pick which Local units go into the team. */
type FirstShare = { id: string; team: string; units: PluginFolderShareUnit[]; note: string; partial: boolean };

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
export function PluginScopeBar({ pluginId, onScopeChanged, active = true, onLiveState }: Props) {
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
  /** A switch to this team is running: getting its files, and in a first share sending ours. */
  const [switching, setSwitching] = useState<{ team: string; sharing: boolean } | null>(null);
  const [share, setShare] = useState<FirstShare | null>(null);
  const [notice, setNotice] = useState("");
  const notify = useRef(onScopeChanged);
  notify.current = onScopeChanged;
  const last = useRef<PluginScopeStatus | null>(null);
  const activeRef = useRef(active);
  activeRef.current = active;
  /** Teammates' changes not told to the panel yet, and the timer that tells them. */
  const untold = useRef<Pending | null>(null);
  const tellTimer = useRef<number | undefined>(undefined);
  /** Pushes waiting for the next status read (with the data they changed), and its timer;
   * `stale`: some came while the panel was hidden. */
  const queued = useRef<{ data: Pending | null } | null>(null);
  const readTimer = useRef<number | undefined>(undefined);
  const stale = useRef(false);

  /** Tell the panel what syncs brought, once a burst settles and only while it is on
   * screen: a hidden panel hears it all in one note when shown again. */
  const tellSoon = useCallback(() => {
    window.clearTimeout(tellTimer.current);
    if (!activeRef.current) return;
    tellTimer.current = window.setTimeout(() => {
      const pending = untold.current;
      const current = last.current;
      if (!pending || !current || current.binding) return;
      untold.current = null;
      notify.current(current, { reason: "synced", ...(pending.keys ? { keys: [...pending.keys].sort() } : {}) });
    }, TELL_SETTLE_MS);
  }, []);

  /** Re-read the bar. Whose data it shows moved (account, Local or a space): the panel
   * starts over at once. Data a sync brought (`data`): the panel merges it ({@link tellSoon}). */
  const refresh = useCallback(async (data: Pending | null = null) => {
    const api = getApi();
    if (!api?.plugin_scope_status) return;
    try {
      const next = await api.plugin_scope_status(pluginId);
      const moved = last.current !== null && scopeKey(next) !== scopeKey(last.current);
      last.current = next;
      rememberPluginLabel(pluginId, next.pluginLabel);
      setStatus(next);
      setNow(Date.now());
      // While a switch gets a team's files the plugin still reads its current copy.
      if (next.binding) return;
      if (moved) {
        untold.current = null;
        window.clearTimeout(tellTimer.current);
        notify.current(next, { reason: "switched" });
      } else if (data) {
        untold.current = mergePending(untold.current, data.keys ? [...data.keys] : null);
        tellSoon();
      }
    } catch {
      /* keep the last bar */
    }
  }, [pluginId, tellSoon]);

  /** One status read per burst of pushes (`data`: keys they changed, null for all, undefined
   * for none); none while hidden, one when shown again. */
  const refreshSoon = useCallback((data: string[] | null | undefined) => {
    const q = queued.current ?? { data: null };
    if (data !== undefined) q.data = mergePending(q.data, data);
    queued.current = q;
    if (!activeRef.current) {
      stale.current = true;
      return;
    }
    window.clearTimeout(readTimer.current);
    readTimer.current = window.setTimeout(() => {
      const run = queued.current;
      queued.current = null;
      void refresh(run?.data ?? null);
    }, REFRESH_SETTLE_MS);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    installPanelPushBus();
    installScopeAlerts(); // refused writes, asks and lost locks are told app-wide (the app installs it too)
    const stopPush = subscribePanelPush((event) => {
      if (event.type === "plugin_scope_changed") {
        if (event.synced) setSyncing(false);
        const plugins = event.plugins ?? [];
        // A teammate's live change: the panel hears it at once (no status read, no settle).
        if (event.live && plugins.includes(pluginId)) {
          const keys = event.keys?.[pluginId];
          if (activeRef.current && last.current && !last.current.binding) {
            notify.current(last.current, { reason: "synced", live: true, ...(keys ? { keys } : {}) });
          } else {
            untold.current = mergePending(untold.current, keys ?? null);
          }
          return;
        }
        // Its data changed: a sync's pull (with the keys it changed), a resolve or restore,
        // or a change for every plugin (no list). A lock, the mode or a round that brought
        // nothing only moves the bar; a switch restarts the panel (the pane reloads it).
        const data = !event.status && !event.switched
          && (plugins.includes(pluginId) || (!event.synced && !plugins.length));
        refreshSoon(data ? event.keys?.[pluginId] ?? null : undefined);
      } else if (event.type === "duckyos_account_changed") {
        refreshSoon(undefined);
      } else if (event.type === "live_peers" && event.plugin === pluginId) {
        refreshSoon(undefined);
      }
    });
    const stopRefused = onRefusedWrite((write, text) => {
      if (write.pluginId === pluginId) setRefused({ write, text });
    });
    return () => {
      stopPush();
      stopRefused();
      window.clearTimeout(readTimer.current);
      window.clearTimeout(tellTimer.current);
    };
  }, [refresh, refreshSoon, pluginId]);

  // Live editing: the pane tells the page, and a remembered Live goes on again by itself.
  const liveNotify = useRef(onLiveState);
  liveNotify.current = onLiveState;
  const liveOn = Boolean(status?.live?.on);
  const liveSupported = Boolean(status?.live?.supported);
  useEffect(() => {
    liveNotify.current?.(liveOn);
  }, [liveOn]);
  const autoLive = useRef(false);
  useEffect(() => {
    if (!liveSupported || liveOn || autoLive.current || !readLiveChoice(pluginId)) return;
    autoLive.current = true;
    void getApi()?.plugin_live_join?.(pluginId, "")?.then(() => refreshSoon(undefined)).catch(() => {});
  }, [liveSupported, liveOn, pluginId, refreshSoon]);

  // Shown again: what came while hidden is read once, and the panel hears it once.
  useEffect(() => {
    if (!active) return;
    if (stale.current) {
      stale.current = false;
      refreshSoon(undefined);
    } else if (untold.current) {
      tellSoon();
    }
  }, [active, refreshSoon, tellSoon]);

  // "12 s ago" keeps moving while the panel is on screen.
  const ticking = Boolean(active && status?.visible && status.scope?.kind === "shared");
  useEffect(() => {
    if (!ticking) return;
    const tick = window.setInterval(() => setNow(Date.now()), AGO_TICK_MS);
    return () => window.clearInterval(tick);
  }, [ticking]);

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

  // While a switch gets a team's files the host notes how far it got: read it each second.
  useEffect(() => {
    if (!switching) return;
    const poll = window.setInterval(() => void refresh(), BINDING_POLL_MS);
    return () => window.clearInterval(poll);
  }, [switching, refresh]);

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
      await refresh(dataChanged ? { keys: null } : null);
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
  // A plugin that can't share has nothing to pick: no bar (older apps sent visible anyway).
  if (!shared && status.shareable === false) return null;
  const refusal = folderRefusal(status);

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
  // A switch running here says so at once; the host's progress fills in the percent. A first
  // share gets the team's files, then sends the picked ones.
  const phrase = !switching
    ? statusPhrase(status, now)
    : status.binding || !switching.sharing
      ? { key: "binding", text: bindingText(status.binding?.team || switching.team, status.binding?.pct), tone: "" as const }
      : { key: "sharing", text: sharingText(switching.team), tone: "" as const };
  // Teams the bar offers to copy Local into: one linked before folders could be shared, or
  // the team this plugin is on, for a project opened since that it has no copy of.
  const offers = status.canChange && !refusal ? status.folderOffers ?? [] : [];
  const help = hasFolders(status) ? `${DATA_AT_REST} ${folderNote(status)}` : DATA_AT_REST;
  const here = shared ? presence(status.people, pluginId) : [];
  const others = othersHere(here);
  const hereLine = hereText(here);
  const locks = shared ? locksText(status.locks) : "";
  const storage = shared ? storageLine(status.usage) : null;
  const manual = shared && status.mode === "manual" && Boolean(api?.plugin_scope_push || api?.plugin_scope_pull);
  const live = shared ? status.live : undefined;
  const canLive = Boolean(live?.supported && api?.plugin_live_join);
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

  /**
   * Switch to Local or a space. A plugin with declared folders gets the team's files first
   * (the bar says so); a team with none of them yet asks which Local units to share
   * (`needs: "first_share"`), and the answer comes back here with `firstShare`. True when
   * the switch happened.
   */
  const switchTo = async (id: string, team: string, firstShare?: PluginScopeFirstShare): Promise<boolean> => {
    setActionError("");
    setNotice("");
    if (team && hasFolders(status)) setSwitching({ team, sharing: Boolean(firstShare?.units?.length) });
    let next: Awaited<ReturnType<NonNullable<PanelApi["plugin_scope_set"]>>> | undefined;
    try {
      const set = getApi()?.plugin_scope_set;
      next = firstShare ? await set?.(pluginId, id, firstShare) : await set?.(pluginId, id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSwitching(null);
    }
    if (next?.needs === "first_share") {
      setShare({
        id, team: next.team || team, units: next.units ?? [], note: next.note || "", partial: Boolean(next.partial),
      });
      return false;
    }
    setShare(null);
    if (next?.ok === false && next.error) {
      setActionError(next.error);
      return false;
    }
    await refresh();
    return true;
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
    await switchTo(choice.id, choice.kind === "shared" ? choice.label : "");
  };

  /** The first share's answer: the dialog closes so the bar can show the copy going in. */
  const answerShare = (firstShare: PluginScopeFirstShare) => {
    if (!share) return;
    setShare(null);
    void switchTo(share.id, share.team, firstShare);
  };

  /** Copy Local into a team (one linked before its folders could be shared, or this team for
   * a project it has no copy of): the first share's picker lists the Local units the team
   * lacks, even when it has files. With none lacking it just switches (nothing to copy). */
  const copyInto = async (offer: { space: string; label: string }) => {
    if (await switchTo(offer.space, offer.label, { pick: true })) {
      setNotice(`${offer.label} already has ${plugin}'s files, so nothing was copied. Your Local copy stays on this PC.`);
    }
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

  /** Go live (everyone live in this plugin sees pointers and changes at once) or leave;
   * the choice is remembered for this plugin on this PC. */
  const goLive = async (on: boolean) => {
    writeLiveChoice(pluginId, on);
    autoLive.current = true;
    await act(async () => (on ? api?.plugin_live_join?.(pluginId, "") : api?.plugin_live_leave?.(pluginId)));
  };

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
        title={help}
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
            disabled={Boolean(switching)}
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
                <>
                  {/* A folder that can't be shared from this PC: no team to offer, and why. */}
                  {refusal && !shared ? <span className="plugin-scope-bar__menu-note">{refusal}</span> : null}
                  {menu.filter((choice) => !(refusal && !shared && choice.kind === "shared")).map((choice) => (
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
                  ))}
                </>
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
        {!switching && api?.plugin_scope_set
          ? offers.map((offer) => (
            <button key={offer.space} type="button" className="plugin-scope-bar__link" disabled={busy}
              onClick={() => void copyInto(offer)}>
              Copy Local into {offer.label}
            </button>
          ))
          : null}
        {notice ? (
          <>
            <span className="plugin-scope-bar__text">{notice}</span>
            <button type="button" className="plugin-scope-bar__link" onClick={() => setNotice("")}>
              Dismiss
            </button>
          </>
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
        {others.length ? (
          <button
            type="button"
            className="plugin-scope-bar__people"
            aria-expanded={drawerOpen}
            aria-controls={drawerId}
            aria-label={`${hereLine}. ${drawerOpen ? "Hide" : "Show"} who is here.`}
            onClick={toggleDrawer}
          >
            <span className="plugin-scope-bar__avatars">
              {others.slice(0, AVATARS_SHOWN).map((row) => (
                <PresenceAvatar key={row.key} row={row} plugin={plugin} labelled={false} />
              ))}
              {others.length > AVATARS_SHOWN ? (
                <span className="plugin-scope-avatar plugin-scope-avatar--more" aria-hidden>
                  +{others.length - AVATARS_SHOWN}
                </span>
              ) : null}
            </span>
            <span className="plugin-scope-bar__here">{hereLine}</span>
          </button>
        ) : null}
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
          {canLive && live?.on ? (
            <>
              <span className="plugin-scope-bar__live" title="Pointers and changes reach everyone live here at once">
                {liveText(live)}
              </span>
              <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void goLive(false)}>
                Leave
              </button>
            </>
          ) : canLive && canSync ? (
            <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void goLive(true)}
              title={`See everyone's pointers in ${plugin} and their changes as they make them`}>
              Go live
            </button>
          ) : null}
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
        <PluginScopeDrawer id={drawerId} pluginId={pluginId} status={status}
          onChanged={(changed) => refresh(changed ? { keys: null } : null)} />
      ) : null}
      {share ? (
        <FolderShareDialog
          plugin={plugin}
          team={share.team}
          units={share.units}
          note={share.note}
          partial={share.partial}
          busy={Boolean(switching)}
          onShare={(units) => answerShare({ units })}
          onStartEmpty={() => answerShare({ start_empty: true })}
          onCancel={() => setShare(null)}
        />
      ) : null}
    </div>
  );
}
