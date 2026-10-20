import { useEffect, useState } from "react";
import "./plugin-ui.css";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { getApi } from "../hooks/usePanelApi";
import type {
  PluginScopeFolderUnit,
  PluginScopeHistoryEntry,
  PluginScopeOutgoing,
  PluginScopeResult,
  PluginScopeStatus,
} from "../types/panel";
import {
  breakConfirm,
  clockText,
  conflictText,
  DATA_AT_REST,
  discardConfirm,
  dropConfirm,
  durationText,
  folderNote,
  folderRefusalText,
  folderUnitKey,
  folderUnitLockId,
  folderUnitStateText,
  formatBytes,
  hasFolders,
  holdsFolderUnit,
  listText,
  liveCellText,
  notShared,
  outgoingStateText,
  presence,
  historyWho,
  presenceText,
  refusedFolders,
  restoreConfirm,
  storageLine,
  unitSizeText,
} from "./scopeBarText";
import { PresenceAvatar } from "./PresenceAvatar";

/** Rows of a long table listed before "Show all". */
const ROWS_SHOWN = 20;
const HISTORY_PAGE = 20;
/** Who the server names as the author of a plugin's move to the new sync (history #1). */
const IMPORTED_BY = "Imported from team data";

type Props = {
  pluginId: string;
  status: PluginScopeStatus;
  /** Re-read the status after an action (`dataChanged`: the plugin's data changed). */
  onChanged: (dataChanged?: boolean) => Promise<void> | void;
  id?: string;
};

type History = { entries: PluginScopeHistoryEntry[]; more: boolean };
type Versions = { kind: string; key: string; entries: PluginScopeHistoryEntry[] };

/** "Oct 17, 3:02 PM". */
function whenText(at?: number): string {
  if (!at) return "";
  return new Date(at * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Changes not sent yet: the engine's list, else the ones a provider held back (refused, blocked). */
function outgoingRows(status: PluginScopeStatus): PluginScopeOutgoing[] {
  return status.changes?.outgoing ?? status.items ?? [];
}

/**
 * The inline drawer under the scope bar (and on Plugins → a plugin → Data): who is here, locks,
 * what goes out and comes in, conflicts, history and the sync mode, each a small table with
 * real buttons. Anything that changes data for everyone asks first.
 */
export function PluginScopeDrawer({ pluginId, status, onChanged, id }: Props) {
  const { confirm } = useConfirmModal();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [compare, setCompare] = useState<{ key: string; text: string } | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const [versions, setVersions] = useState<Versions | null>(null);
  const [message, setMessage] = useState("");
  const [allRows, setAllRows] = useState(false);

  // Opening the drawer has the space looked at again (heads, presence) once; what that
  // brings arrives as a status refresh. Never per status: each look starts a round.
  useEffect(() => {
    void getApi()?.plugin_scope_activity?.(pluginId).catch(() => undefined);
  }, [pluginId]);

  const s = status;
  const api = getApi();
  const scope = s.scope;
  const label = scope?.label || "this space";
  const plugin = s.pluginLabel || pluginId;
  const state = s.state || "";
  const lost = state === "lost";
  const reset = state === "reset";
  // History, Mode and locks are the new sync's; a copy still on the older one has none.
  const v2 = s.engine ? s.engine === "v2" : s.mode !== undefined || typeof s.head === "number";

  /** One action; its error stays in the drawer until the next one. True when it worked. */
  const act = async (run: () => Promise<PluginScopeResult | undefined>, dataChanged = false, done = ""): Promise<boolean> => {
    setError("");
    setNote("");
    setBusy(true);
    try {
      const res = await run();
      if (res?.ok === false) {
        setError(res.error || "That didn't work. Try again.");
        return false;
      }
      if (done) setNote(done);
      await onChanged(dataChanged);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  // ---------------------------------------------------------------- locks
  const release = (unit: string) => act(async () => api?.plugin_scope_unlock?.(pluginId, unit));
  const ask = (unit: string, holder: string, name: string) =>
    act(async () => api?.plugin_scope_ask?.(pluginId, unit), false, `Asked ${holder} to release ${name}.`);
  const breakLock = async (unit: string, holder: string, name: string) => {
    const ok = await confirm({ ...breakConfirm(holder, name), confirmLabel: "Break lock", danger: true });
    if (ok !== true) return;
    await act(async () => api?.plugin_scope_break?.(pluginId, unit));
  };
  const lockUnit = (unit: string, name: string) => act(async () => api?.plugin_scope_lock?.(pluginId, unit, name));

  // ---------------------------------------------------------------- folder units changed while held
  const keepCopy = (f: PluginScopeFolderUnit) =>
    act(async () => api?.plugin_scope_resolve?.(pluginId, "tree", folderUnitKey(f), "keep_copy"), true,
      `Your version of ${f.name} is kept beside it as a copy; ${f.name} has ${label}'s version again.`);
  const discard = async (f: PluginScopeFolderUnit) => {
    const ok = await confirm({ ...discardConfirm(f.name, label), confirmLabel: "Discard mine", danger: true });
    if (ok !== true) return;
    await act(async () => api?.plugin_scope_resolve?.(pluginId, "tree", folderUnitKey(f), "discard"), true);
  };

  // ---------------------------------------------------------------- changes
  const retry = async (key?: string) => {
    const run = async () => (key ? api?.plugin_scope_retry?.(pluginId, key) : api?.plugin_scope_retry?.(pluginId));
    if (await act(run)) void api?.plugin_scope_sync?.(pluginId, true);
  };
  const drop = async (row: PluginScopeOutgoing) => {
    const ok = await confirm({ ...dropConfirm(label, row.name || row.key), confirmLabel: "Drop my change", danger: true });
    if (ok !== true) return;
    await act(async () => api?.plugin_scope_drop?.(pluginId, row.kind, row.key), true);
  };
  const redownload = (kind: string, key: string) => act(async () => api?.plugin_scope_pull?.(pluginId, kind, key), true);

  // ---------------------------------------------------------------- conflicts
  const resolve = async (kind: string, key: string, name: string, choice: "mine" | "theirs" | "both", by: string) => {
    if (choice === "theirs") {
      const ok = await confirm({
        title: `Keep ${by}'s version of ${name}?`,
        message: "Your version here is not kept.",
        confirmLabel: "Keep theirs",
        danger: true,
      });
      if (ok !== true) return;
    }
    if (compare?.key === key) setCompare(null);
    await act(async () => api?.plugin_scope_resolve?.(pluginId, kind, key, choice), true);
  };
  const showCompare = async (kind: string, key: string) => {
    if (compare?.key === key) {
      setCompare(null);
      return;
    }
    setError("");
    try {
      const res = await api?.plugin_scope_resolve?.(pluginId, kind, key, "compare");
      if (res?.ok === false) setError(res.error || "Couldn't compare them.");
      else setCompare({ key, text: res?.diff || "No difference to show." });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  // ---------------------------------------------------------------- history
  const loadHistory = async (before?: number) => {
    setError("");
    try {
      const res = await api?.plugin_scope_history?.(pluginId, { before, limit: HISTORY_PAGE });
      if (!res || res.ok === false) {
        setError(res?.error || "Couldn't load the history.");
        return;
      }
      setHistory((prev) => ({
        entries: [...(before && prev ? prev.entries : []), ...(res.entries ?? [])],
        more: Boolean(res.more),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const loadVersions = async (kind: string, key: string) => {
    setError("");
    try {
      const res = await api?.plugin_scope_history?.(pluginId, { kind, key, limit: HISTORY_PAGE });
      if (!res || res.ok === false) setError(res?.error || "Couldn't load its versions.");
      else setVersions({ kind, key, entries: res.entries ?? [] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const restore = async (action: "item" | "to" | "undo", seq: number, item?: { kind: string; key: string }) => {
    const question = restoreConfirm(action, label, { plugin, seq, key: item?.key });
    const ok = await confirm({ ...question, confirmLabel: action === "undo" ? "Undo" : "Restore" });
    if (ok !== true) return;
    const request = action === "item" && item ? { items: [{ ...item, seq }] } : action === "undo" ? { undoSeq: seq } : { toSeq: seq };
    let skipped = 0;
    const worked = await act(async () => {
      const res = await api?.plugin_scope_restore?.(pluginId, request);
      skipped = res?.skipped?.length ?? 0;
      return res;
    }, true);
    if (!worked) return;
    setNote(skipped
      ? `Restored. ${skipped} ${skipped === 1 ? "item wasn't" : "items weren't"}: ${skipped === 1 ? "its version is" : "their versions are"} no longer kept.`
      : "Restored.");
    if (history) void loadHistory();
  };

  // ---------------------------------------------------------------- mode
  const setMode = (mode: "auto" | "manual") => act(async () => api?.plugin_scope_mode?.(pluginId, mode));
  const push = async () => {
    if (await act(async () => api?.plugin_scope_push?.(pluginId, message.trim()))) setMessage("");
  };
  const pull = () => act(async () => api?.plugin_scope_pull?.(pluginId), true);

  // ---------------------------------------------------------------- lost access
  const saveUnsent = async () => {
    let saved = 0;
    const worked = await act(async () => {
      const res = await api?.plugin_scope_save_unsent?.(pluginId, "save");
      saved = res?.saved?.length ?? 0;
      return res;
    });
    if (worked) setNote(`Saved ${saved} ${saved === 1 ? "change" : "changes"} to Local.`);
  };
  const discardUnsent = async () => {
    const ok = await confirm({
      title: "Let your unsent changes go?",
      message: `They are never sent, and they leave this PC with ${label}'s copy.`,
      confirmLabel: "Let them go",
      danger: true,
    });
    if (ok !== true) return;
    await act(async () => api?.plugin_scope_save_unsent?.(pluginId, "discard"));
  };

  const storage = storageLine(s.usage);
  const summary = [
    s.email ? `Signed in as ${s.email}` : "",
    s.members ? `${s.members} member${s.members === 1 ? "" : "s"}` : "",
  ].filter(Boolean).join(" · ");
  const people = presence(s.people, pluginId);
  const locks = s.locks ?? [];
  const outgoing = outgoingRows(s);
  const shownOut = allRows ? outgoing : outgoing.slice(0, ROWS_SHOWN);
  // Retry and Drop my change are for data items; a folder unit the server kept failing has
  // Retry too. Any other held folder unit says what fixes it.
  const fixable = outgoing.filter((row) => row.state === "blocked" || (row.kind !== "tree" && row.state === "refused"));
  const canFix = !reset;
  const changes = s.changes ?? {};
  const blockedIn = changes.blocked ?? [];
  const conflicts = s.conflicts ?? [];
  const folders = s.folders ?? [];
  const refusals = refusedFolders(s);
  const pending = typeof s.pending === "number" ? s.pending : outgoing.filter((row) => row.state === "queued").length;
  const retryAll = canFix && fixable.length > 1 && Boolean(api?.plugin_scope_retry);
  // A provider lists the newest held changes only; the count is all of them.
  const unlisted = s.changes?.outgoing ? 0 : notShared(s).count - outgoing.length;
  const offerSave = lost && Boolean(api?.plugin_scope_save_unsent) && !s.unsentChosen && s.unsent !== 0;
  const manual = s.mode === "manual";

  return (
    <div className="plugin-scope-drawer" id={id} role="region" aria-label={`Sync details: ${label}`}>
      {summary || storage ? (
        <p className="plugin-scope-drawer__line">
          {summary ? <span>{summary}</span> : null}
          {storage ? (
            <span className={`plugin-scope-bar__storage plugin-scope-bar__storage--${storage.level}`}>
              <progress className="plugin-scope-bar__meter" value={storage.pct} max={100} aria-label="Storage used" />
              <span>{storage.text}</span>
              {storage.note ? <strong>{storage.note}</strong> : null}
            </span>
          ) : null}
        </p>
      ) : null}
      {error ? <p className="plugin-scope-drawer__error" role="alert">{error}</p> : null}
      {note ? <p className="plugin-scope-drawer__note">{note}</p> : null}

      {offerSave ? (
        <section className="plugin-scope-drawer__section" aria-label="Unsent changes">
          <p className="plugin-scope-drawer__line">
            {s.unsent
              ? `${s.unsent} ${s.unsent === 1 ? "change" : "changes"} made here never reached ${label}.`
              : `Changes made here may not have reached ${label}.`}{" "}
            Keep them in your Local copy before {label}&apos;s data leaves this PC.
          </p>
          <p className="plugin-scope-drawer__line">
            <button type="button" className="plugin-scope-drawer__btn" disabled={busy} onClick={() => void saveUnsent()}>
              Save my unsent changes to Local
            </button>
            <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void discardUnsent()}>
              Let them go
            </button>
          </p>
        </section>
      ) : null}

      {s.people !== undefined ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">People in {label}</h4>
          {people.length ? (
            <table className="plugin-scope-drawer__table plugin-scope-drawer__table--people">
              <thead>
                <tr><th>Member</th><th>PC</th><th>In {plugin}</th>{s.live?.supported ? <th>Live</th> : null}<th>Since</th></tr>
              </thead>
              <tbody>
                {people.map((row) => (
                  <tr key={row.key} className={`plugin-scope-people--${row.state}`}>
                    <td>
                      <span className="plugin-scope-people__who">
                        <PresenceAvatar row={row} plugin={plugin} labelled={false} />
                        <span>{row.me || row.self ? `You (${row.name})` : row.name}</span>
                      </span>
                    </td>
                    <td>{row.device}</td>
                    <td className="plugin-scope-people__doing">{presenceText(row, plugin)}</td>
                    {s.live?.supported ? <td>{liveCellText(row, s.live)}</td> : null}
                    <td>{row.since ? clockText(row.since) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="plugin-scope-drawer__empty">Nobody else is here right now.</p>
          )}
          {people.length && people.every((row) => row.me) ? (
            <p className="plugin-scope-drawer__empty">Nobody else is here right now.</p>
          ) : null}
        </section>
      ) : null}

      {s.live?.on ? (
        <p className="plugin-scope-drawer__note">
          Live: pointers and changes go straight between your PCs. Saved changes still sync as usual.
        </p>
      ) : null}

      {s.locks !== undefined ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">Locks</h4>
          {locks.length ? (
            <table className="plugin-scope-drawer__table">
              <thead>
                <tr><th>Unit</th><th>Holder</th><th>Since</th><th>Lease left</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {locks.map((lock) => {
                  const name = lock.name || lock.unit;
                  // This account on another PC: the buttons ask that PC by its name.
                  const holder = lock.elsewhere || lock.holder || "someone";
                  return (
                    <tr key={lock.unit}>
                      <td>{name}</td>
                      <td>{lock.mine ? "You" : lock.elsewhere ? `You on ${lock.elsewhere}` : holder}</td>
                      <td>{lock.since ? clockText(lock.since) : ""}</td>
                      <td>{lock.leaseLeft != null ? (lock.leaseLeft > 0 ? durationText(lock.leaseLeft) : "Ran out") : ""}</td>
                      <td className="plugin-scope-drawer__actions">
                        {lock.mine ? (
                          api?.plugin_scope_unlock ? (
                            <button type="button" className="plugin-scope-bar__link" disabled={busy}
                              aria-label={`Release ${name}`} onClick={() => void release(lock.unit)}>
                              Release
                            </button>
                          ) : null
                        ) : (
                          <>
                            {api?.plugin_scope_ask ? (
                              <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                aria-label={`Ask ${holder} to release ${name}`} onClick={() => void ask(lock.unit, holder, name)}>
                                Ask to release
                              </button>
                            ) : null}
                            {api?.plugin_scope_break ? (
                              <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                aria-label={`Break ${holder}'s lock on ${name}`} onClick={() => void breakLock(lock.unit, holder, name)}>
                                Break
                              </button>
                            ) : null}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p className="plugin-scope-drawer__empty">Nothing is locked.</p>
          )}
        </section>
      ) : null}

      {!lost ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">Changes</h4>
          {outgoing.length ? (
            <>
              <table className="plugin-scope-drawer__table">
                <thead>
                  <tr><th>Item</th><th>Size</th><th>State</th><th><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody>
                  {shownOut.map((row) => {
                    const name = row.name || row.key;
                    const fix = canFix && fixable.includes(row);
                    return (
                      <tr key={`${row.kind}:${row.key}`}>
                        <td>{name}{row.deleted ? " (deleted here)" : ""}</td>
                        <td>{row.size ? formatBytes(row.size) : row.files ? unitSizeText(row.files) : ""}</td>
                        <td>{outgoingStateText(row.state, row.reason, row.attempts)}</td>
                        <td className="plugin-scope-drawer__actions">
                          {fix && api?.plugin_scope_retry ? (
                            <button type="button" className="plugin-scope-bar__link" disabled={busy}
                              aria-label={`Retry ${name}`} onClick={() => void retry(row.key)}>
                              Retry
                            </button>
                          ) : null}
                          {fix && row.kind !== "tree" && api?.plugin_scope_drop ? (
                            <button type="button" className="plugin-scope-bar__link" disabled={busy}
                              aria-label={`Drop my change to ${name}`} onClick={() => void drop(row)}>
                              Drop my change
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {retryAll || outgoing.length > ROWS_SHOWN || unlisted > 0 ? (
                <p className="plugin-scope-drawer__line">
                  {retryAll ? (
                    <button type="button" className="plugin-scope-bar__link" disabled={busy} onClick={() => void retry()}>
                      Retry all
                    </button>
                  ) : null}
                  {outgoing.length > ROWS_SHOWN ? (
                    <button type="button" className="plugin-scope-bar__link" aria-expanded={allRows} onClick={() => setAllRows(!allRows)}>
                      {allRows ? "Show fewer" : `Show all ${outgoing.length}`}
                    </button>
                  ) : null}
                  {unlisted > 0 ? <span>{unlisted} more not listed</span> : null}
                </p>
              ) : null}
            </>
          ) : (
            <p className="plugin-scope-drawer__empty">{pending ? `${pending} to send.` : "Nothing to send."}</p>
          )}
          {changes.incoming ? (
            <p className="plugin-scope-drawer__line">
              <span>
                {changes.incoming} incoming{changes.incomingBy?.length ? ` from ${listText(changes.incomingBy)}` : ""}
                {changes.held ? " · they wait until you update" : ""}
              </span>
              {changes.held && api?.plugin_scope_pull ? (
                <button type="button" className="plugin-scope-bar__link" disabled={busy || reset} onClick={() => void pull()}>
                  Update now
                </button>
              ) : null}
            </p>
          ) : null}
          {blockedIn.length ? (
            <table className="plugin-scope-drawer__table" aria-label="Incoming items that couldn't be applied">
              <thead>
                <tr><th>Incoming item</th><th>Problem</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {blockedIn.map((row) => {
                  const name = row.name || row.key;
                  return (
                    <tr key={`${row.kind}:${row.key}`}>
                      <td>{name}</td>
                      <td>{row.error || "Couldn't be applied here"}{row.attempts ? ` (${row.attempts} tries)` : ""}</td>
                      <td className="plugin-scope-drawer__actions">
                        {api?.plugin_scope_pull ? (
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`Re-download ${name}`} onClick={() => void redownload(row.kind, row.key)}>
                            Re-download
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}

      {conflicts.length ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">Conflicts</h4>
          <table className="plugin-scope-drawer__table">
            <thead>
              <tr><th>Item</th><th>What happened</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {conflicts.map((c) => {
                const name = c.name || c.key;
                const by = c.by || "someone";
                const deleted = c.reason === "deleted";
                return [
                  <tr key={`${c.kind}:${c.key}`}>
                    <td>{name}</td>
                    <td>{conflictText(c.reason, c.by)}{c.at ? ` · ${clockText(c.at)}` : ""}</td>
                    <td className="plugin-scope-drawer__actions">
                      {api?.plugin_scope_resolve ? (
                        <>
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`${deleted ? "Restore mine" : "Keep mine"}: ${name}`}
                            onClick={() => void resolve(c.kind, c.key, name, "mine", by)}>
                            {deleted ? "Restore mine" : "Keep mine"}
                          </button>
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`${deleted ? "Accept delete" : "Keep theirs"}: ${name}`}
                            onClick={() => void resolve(c.kind, c.key, name, "theirs", by)}>
                            {deleted ? "Accept delete" : "Keep theirs"}
                          </button>
                          {c.kind === "tree" ? (
                            <button type="button" className="plugin-scope-bar__link" disabled={busy}
                              aria-label={`Keep both: ${name}`} onClick={() => void resolve(c.kind, c.key, name, "both", by)}>
                              Keep both
                            </button>
                          ) : null}
                          <button type="button" className="plugin-scope-bar__link" aria-expanded={compare?.key === c.key}
                            aria-label={`Compare: ${name}`} onClick={() => void showCompare(c.kind, c.key)}>
                            Compare
                          </button>
                        </>
                      ) : null}
                    </td>
                  </tr>,
                  compare?.key === c.key ? (
                    <tr key={`${c.kind}:${c.key}:compare`}>
                      <td colSpan={3}><pre className="plugin-scope-drawer__diff">{compare.text}</pre></td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {v2 && api?.plugin_scope_history ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">History</h4>
          {versions ? (
            <>
              <p className="plugin-scope-drawer__line">
                <span>Versions of {versions.key}</span>
                <button type="button" className="plugin-scope-bar__link" onClick={() => setVersions(null)}>Back to history</button>
              </p>
              <table className="plugin-scope-drawer__table">
                <thead>
                  <tr><th>#</th><th>Who</th><th>When</th><th>Size</th><th><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody>
                  {versions.entries.map((v) => (
                    <tr key={v.seq}>
                      <td>#{v.seq}</td>
                      <td>{historyWho(v)}</td>
                      <td>{whenText(v.at)}</td>
                      <td>{v.deleted ? "Deleted" : v.size ? formatBytes(v.size) : ""}</td>
                      <td className="plugin-scope-drawer__actions">
                        {api?.plugin_scope_restore ? (
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`Restore ${versions.key} to #${v.seq}`}
                            onClick={() => void restore("item", v.seq, { kind: versions.kind, key: versions.key })}>
                            Restore item
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : history ? (
            <>
              {history.entries.length ? (
                <table className="plugin-scope-drawer__table">
                  <thead>
                    <tr><th>#</th><th>Who</th><th>Device</th><th>When</th><th>Message</th><th>Items</th><th><span className="sr-only">Actions</span></th></tr>
                  </thead>
                  <tbody>
                    {history.entries.map((e) => [
                      <tr key={e.seq}>
                        <td>#{e.seq}</td>
                        <td>{historyWho(e)}</td>
                        <td>{e.device || ""}</td>
                        <td>{whenText(e.at)}</td>
                        <td>{e.message || ""}</td>
                        <td>
                          {e.items?.length ? (
                            <button type="button" className="plugin-scope-bar__link" aria-expanded={openSeq === e.seq}
                              onClick={() => setOpenSeq(openSeq === e.seq ? null : e.seq)}>
                              {e.count ?? e.items.length}
                            </button>
                          ) : (e.count ?? "")}
                        </td>
                        <td className="plugin-scope-drawer__actions">
                          {api?.plugin_scope_restore ? (
                            <>
                              {/* The move to the new sync can't be undone (the server refuses it too). */}
                              {e.seq === 1 && e.by === IMPORTED_BY ? null : (
                                <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                  aria-label={`Undo #${e.seq}`} onClick={() => void restore("undo", e.seq)}>
                                  Undo
                                </button>
                              )}
                              <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                aria-label={`Restore to #${e.seq}`} onClick={() => void restore("to", e.seq)}>
                                Restore to here
                              </button>
                            </>
                          ) : null}
                        </td>
                      </tr>,
                      openSeq === e.seq ? (
                        <tr key={`${e.seq}:items`}>
                          <td colSpan={7}>
                            <ul className="plugin-scope-drawer__items">
                              {(e.items ?? []).map(([kind, key]) => (
                                <li key={`${kind}:${key}`}>
                                  <span>{key}</span>
                                  <button type="button" className="plugin-scope-bar__link"
                                    aria-label={`Versions of ${key}`} onClick={() => void loadVersions(kind, key)}>
                                    Versions
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      ) : null,
                    ])}
                  </tbody>
                </table>
              ) : (
                <p className="plugin-scope-drawer__empty">No history yet.</p>
              )}
              {history.more ? (
                <button type="button" className="plugin-scope-bar__link"
                  onClick={() => void loadHistory(history.entries[history.entries.length - 1]?.seq)}>
                  Older
                </button>
              ) : null}
            </>
          ) : (
            <button type="button" className="plugin-scope-bar__link" onClick={() => void loadHistory()}>
              Show history
            </button>
          )}
        </section>
      ) : null}

      {folders.length || refusals.length ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">Folder units</h4>
          {refusals.map((folder) => (
            <p key={folder.id} className="plugin-scope-drawer__line plugin-scope-bar__text--warn">
              {refusals.length > 1 ? `${folder.id}: ` : ""}{folderRefusalText(folder.refused || "")}
            </p>
          ))}
          {folders.length ? (
            <table className="plugin-scope-drawer__table">
              <thead>
                <tr><th>Unit</th><th>Size</th><th>State</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {folders.map((f) => {
                  const held = f.state === "quarantined";
                  const holder = f.elsewhere || f.holder || "the holder";
                  const lockId = folderUnitLockId(f);
                  const mine = holdsFolderUnit(f, locks);
                  const theirs = !mine && (f.state === "locked" || f.state === "locked_by");
                  return (
                    <tr key={`${f.folder_id ?? ""}:${f.unit}`}>
                      <td>{f.name}</td>
                      <td>{unitSizeText(f.files, f.bytes)}</td>
                      <td>{folderUnitStateText(f)}</td>
                      <td className="plugin-scope-drawer__actions">
                        {held ? (
                          <>
                            {api?.plugin_scope_ask ? (
                              <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                aria-label={`Ask ${holder} to release ${f.name}`}
                                onClick={() => void ask(lockId, f.elsewhere || f.holder || "them", f.name)}>
                                Ask to release
                              </button>
                            ) : null}
                            {api?.plugin_scope_resolve ? (
                              <>
                                <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                  aria-label={`Keep mine as a copy: ${f.name}`} onClick={() => void keepCopy(f)}>
                                  Keep mine as a copy
                                </button>
                                <button type="button" className="plugin-scope-bar__link" disabled={busy}
                                  aria-label={`Discard mine: ${f.name}`} onClick={() => void discard(f)}>
                                  Discard mine
                                </button>
                              </>
                            ) : null}
                          </>
                        ) : mine && api?.plugin_scope_unlock ? (
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`Release ${f.name}`} onClick={() => void release(lockId)}>
                            Release
                          </button>
                        ) : !theirs && f.state !== "refused" && api?.plugin_scope_lock ? (
                          <button type="button" className="plugin-scope-bar__link" disabled={busy}
                            aria-label={`Lock ${f.name}`} onClick={() => void lockUnit(lockId, f.name)}>
                            Lock
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}

      {v2 && !lost && api?.plugin_scope_mode ? (
        <section className="plugin-scope-drawer__section">
          <h4 className="plugin-scope-drawer__title">Mode</h4>
          <div className="plugin-scope-drawer__line" role="radiogroup" aria-label="Sync mode">
            <button type="button" role="radio" aria-checked={!manual} className="plugin-scope-drawer__choice"
              disabled={busy} onClick={() => { if (manual) void setMode("auto"); }}>
              Auto
            </button>
            <button type="button" role="radio" aria-checked={manual} className="plugin-scope-drawer__choice"
              disabled={busy} onClick={() => { if (!manual) void setMode("manual"); }}>
              Manual
            </button>
            <span>{manual ? "Changes go out and come in only when you push or pull." : "Changes go out and come in by themselves."}</span>
          </div>
          {manual ? (
            <div className="plugin-scope-drawer__line">
              <input
                type="text"
                className="plugin-scope-drawer__input"
                aria-label="Push message (optional)"
                placeholder="Message (optional)"
                value={message}
                maxLength={200}
                onChange={(event) => setMessage(event.target.value)}
              />
              {api?.plugin_scope_push ? (
                <button type="button" className="plugin-scope-drawer__btn" disabled={busy || reset} onClick={() => void push()}>
                  Push
                </button>
              ) : null}
              {api?.plugin_scope_pull ? (
                <button type="button" className="plugin-scope-drawer__btn" disabled={busy || reset} onClick={() => void pull()}>
                  Pull
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      <p className="plugin-scope-drawer__help">{DATA_AT_REST}</p>
      {hasFolders(s) ? <p className="plugin-scope-drawer__help">{folderNote(s)}</p> : null}
    </div>
  );
}
