import { useCallback, useEffect, useState } from "react";
import { getApi } from "../../../hooks/usePanelApi";
import { installPanelPushBus, subscribePanelPush } from "../../../hooks/usePanelPushBus";
import { Icons } from "../../../icons/Icons";
import { formatBytes, syncText } from "../../../plugin-ui/scopeBarText";
import type { PluginDataTotals, PluginScopeChoice, PluginScopeStatus } from "../../../types/panel";

/** "12 docs · 3 files · 4.2 MB", or that nothing is stored. */
export function totalsText(t: PluginDataTotals | undefined): string {
  const docs = t?.docs ?? 0;
  const files = t?.files ?? 0;
  if (!docs && !files) return "Nothing stored";
  const bytes = (t?.docsBytes ?? 0) + (t?.filesBytes ?? 0);
  return `${docs} doc${docs === 1 ? "" : "s"} · ${files} file${files === 1 ? "" : "s"} · ${formatBytes(bytes)}`;
}

function readOnlyText(status: PluginScopeStatus): string {
  if (status.state === "locked") return "Waiting for your account's data key. Read-only until you're back online.";
  if (status.state === "waiting") return "Waiting for team data. Read-only until it arrives.";
  if (status.scope?.readOnly) return "Team Private is paused for this team. Read-only.";
  return "";
}

type Confirm = { kind: "switch"; choice: PluginScopeChoice } | { kind: "copy" };

/**
 * Plugins page → a plugin → Data: where its data lives (Local or one team, picked per
 * plugin), how much there is, and a one-way copy of the Local data into that team.
 * Every team keeps its own copy; nothing moves between teams. Renders nothing for
 * accounts without the Teams beta (rule 13).
 */
export function PluginDataPanel({ pluginId, name }: { pluginId: string; name: string }) {
  const [status, setStatus] = useState<PluginScopeStatus | null>(null);
  const [choices, setChoices] = useState<PluginScopeChoice[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const next = await getApi()?.plugin_scope_status?.(pluginId);
      if (next) setStatus(next);
    } catch {
      /* keep what is shown */
    }
  }, [pluginId]);

  useEffect(() => {
    void refresh();
    installPanelPushBus();
    return subscribePanelPush((event) => {
      if (event.type === "plugin_scope_changed" && (!event.plugins?.length || event.plugins.includes(pluginId))) void refresh();
      else if (event.type === "duckyos_account_changed") void refresh();
    });
  }, [refresh, pluginId]);

  if (!status?.visible || !status.scope) return null;
  const scope = status.scope;
  const team = scope.kind === "team";
  const where = team ? `Team · ${scope.label}` : "Local";
  const locked = readOnlyText(status);
  const localCount = (status.local?.docs ?? 0) + (status.local?.files ?? 0);

  const openPicker = async () => {
    setPicking((open) => !open);
    setConfirm(null);
    if (choices) return;
    const res = await getApi()?.plugin_scope_choices?.();
    setChoices(res?.choices ?? []);
  };

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    try {
      setMessage(await work());
    } finally {
      setBusy(false);
      setConfirm(null);
      await refresh();
    }
  };

  const switchTo = (choice: PluginScopeChoice) =>
    run(async () => {
      const res = await getApi()?.plugin_scope_set?.(pluginId, choice.id);
      setPicking(false);
      if (res?.ok === false) return res.error || "Could not switch.";
      return choice.kind === "team" ? `${name} now shows ${choice.label}'s copy.` : `${name} now shows your Local copy.`;
    });

  const copyIn = () =>
    run(async () => {
      const res = await getApi()?.plugin_data_copy_to_team?.(pluginId, scope.teamId);
      if (!res || res.ok === false) return res?.error || "Could not copy.";
      const kept = res.kept ? ` ${res.kept} ${res.kept === 1 ? "item" : "items"} ${scope.label} already had stayed as they were.` : "";
      return `Copied ${res.copied ?? 0} ${res.copied === 1 ? "item" : "items"} into ${scope.label}.${kept}`;
    });

  return (
    <div className="ds-panel ds-data">
      <h3 className="ds-panel-title">Data</h3>
      <p className="ds-data-where">
        <span className={`ds-data-pill ds-data-pill--${team ? "team" : "local"}`}>
          {team ? <Icons.Users /> : <Icons.Monitor />}
          {where}
        </span>
        <span className="ds-data-help">
          {team ? "Every member sees and changes the same copy." : "Only on this PC, for your account."}
        </span>
      </p>
      <dl className="ds-data-totals">
        {team ? (
          <>
            <dt>{scope.label}</dt>
            <dd>
              {totalsText(status.current)}
              <span className="ds-data-sync">{syncText(status, Date.now())}</span>
            </dd>
          </>
        ) : null}
        <dt>Local</dt>
        <dd>{totalsText(status.local)}{team ? <span className="ds-data-sync">Separate copy on this PC</span> : null}</dd>
      </dl>
      {locked ? <p className="ds-data-note" role="note"><Icons.Lock /> {locked}</p> : null}

      <div className="ds-data-actions">
        {status.canChange ? (
          <button type="button" className="ds-btn ds-data-btn" aria-expanded={picking} onClick={() => void openPicker()} disabled={busy}>
            Keep data in…
          </button>
        ) : null}
        {team && !locked ? (
          <button type="button" className="ds-btn ds-data-btn" disabled={busy || !localCount} title={localCount ? undefined : "Your Local copy is empty"}
            onClick={() => { setPicking(false); setConfirm({ kind: "copy" }); }}>
            Copy Local data into {scope.label}
          </button>
        ) : null}
        {team && status.teamSlug ? (
          <button type="button" className="ds-btn ds-data-btn" onClick={() => void getApi()?.plugin_data_open_web?.(pluginId)}>
            <Icons.Globe /> View on the web
          </button>
        ) : null}
      </div>

      {picking ? (
        <div className="ds-data-choices" role="radiogroup" aria-label={`Keep ${name}'s data in`}>
          {choices === null ? <p className="ds-data-help">Loading your teams…</p> : null}
          {(choices ?? []).map((choice) => {
            const current = choice.kind === "team" ? scope.teamId === choice.id : !team;
            return (
              <button key={choice.id} type="button" role="radio" aria-checked={current} className="ds-data-choice"
                disabled={busy} onClick={() => { if (!current) setConfirm({ kind: "switch", choice }); }}>
                {choice.kind === "team" ? <Icons.Users /> : <Icons.Monitor />}
                <span>{choice.kind === "team" ? `Team · ${choice.label}` : "Local"}</span>
                {choice.members ? <small>{choice.members} members</small> : null}
              </button>
            );
          })}
          {choices && choices.length === 1 ? (
            <p className="ds-data-help">No team with Team Private yet. Teams that have it show here.</p>
          ) : null}
        </div>
      ) : null}

      {confirm ? (
        <div className="ds-data-confirm" role="alertdialog" aria-label="Confirm">
          <p>
            {confirm.kind === "copy"
              ? `Copy your Local ${name} data into ${scope.label}? Items ${scope.label} already has are kept. Nothing goes to any other team.`
              : confirm.choice.kind === "team"
                ? `Show ${confirm.choice.label}'s copy of ${name}? Your Local copy stays on this PC, separate. Nothing is copied.`
                : `Show your Local copy of ${name}? ${scope.label}'s copy stays with the team.`}
          </p>
          <button type="button" className="ds-btn ds-data-btn ds-data-btn--primary" disabled={busy}
            onClick={() => void (confirm.kind === "copy" ? copyIn() : switchTo(confirm.choice))}>
            {confirm.kind === "copy" ? "Copy" : "Switch"}
          </button>
          <button type="button" className="ds-btn ds-data-btn" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button>
        </div>
      ) : null}

      {message ? <p className="ds-data-help" role="status">{message}</p> : null}
      <p className="ds-data-help">Each team keeps its own copy. Data never moves between teams.</p>
    </div>
  );
}
