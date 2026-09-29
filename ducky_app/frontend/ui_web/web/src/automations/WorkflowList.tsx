import { useState, type Ref } from "react";
import { getApi } from "../hooks/usePanelApi";
import type { AutomationSummaryDto, PluginScopeStatus, WorkflowOwnerDto, WorkflowOwnersDto } from "../types/panel";
import { Icons } from "../icons/Icons";
import { syncText } from "../plugin-ui/scopeBarText";

export const LOCAL_OWNER: WorkflowOwnerDto = { id: "local", kind: "local", label: "Local" };

export function ownerName(owner: WorkflowOwnerDto | undefined): string {
  return owner?.kind === "team" ? `Team · ${owner.label}` : "Local";
}

export function OwnerIcon({ owner }: { owner: WorkflowOwnerDto | undefined }) {
  return owner?.kind === "team" ? <Icons.Users /> : <Icons.Monitor />;
}

/** Who can see it, in words (tooltips on the folder and the toolbar chip). */
export function ownerHelp(owner: WorkflowOwnerDto | undefined): string {
  if (owner?.kind !== "team") return "Local: only on this PC, for your account. Not shared.";
  const who = `Team ${owner.label}: every member sees it and changes sync to the team.`;
  return owner.readOnly && owner.reason ? `${who} ${owner.reason}` : who;
}

/** The folder's second line: where a team copy stands, or that Local stays here. */
export function folderStatus(owner: WorkflowOwnerDto, nowMs: number): string {
  if (owner.kind !== "team") return "Only on this PC";
  if (owner.state === "waiting") return "Waiting for team data";
  if (owner.state === "locked") return "Waiting for your data key";
  if (owner.state === "paused") return "Team Private paused";
  const sync = owner.sync || {};
  return syncText({ state: sync.state, pending: sync.pending, syncedAt: sync.syncedAt ?? null } as PluginScopeStatus, nowMs);
}

function TriggerBadge({ row }: { row: AutomationSummaryDto }) {
  const trigger = row.trigger || { kind: "manual", label: "Manual" };
  const teamRun = row.owner?.kind === "team" && (trigger.kind === "schedule" || trigger.kind === "event");
  const here = teamRun ? (row.run_here ? " · runs on this PC" : " · not on this PC") : "";
  return (
    <span className={`aw-trigger aw-trigger--${trigger.kind}${teamRun && !row.run_here ? " is-elsewhere" : ""}`} title={`Starts from: ${trigger.label}${here}`}>
      {trigger.label}
    </span>
  );
}

type Props = {
  listId: string;
  listRef: Ref<HTMLElement>;
  owners: WorkflowOwnersDto;
  rows: AutomationSummaryDto[];
  activeId: string;
  collapsed: boolean;
  nowMs: number;
  onToggleCollapsed: () => void;
  onOpen: (id: string) => void;
  onCreate: (ownerId: string) => void;
  onImportLocal: () => void;
};

/** Workflows sidebar: one folder per owner (Local, then each team). */
export function WorkflowList({ listId, listRef, owners, rows, activeId, collapsed, nowMs, onToggleCollapsed, onOpen, onCreate, onImportLocal }: Props) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const folders = owners.owners?.length ? owners.owners : [LOCAL_OWNER];
  return (
    <aside className="aw-list" ref={listRef} aria-label="Workflows">
      <div className="aw-list-head">
        <button type="button" className="aw-list-toggle" title={collapsed ? "Expand Workflows" : "Collapse Workflows"} aria-expanded={!collapsed} aria-controls={listId} onClick={onToggleCollapsed}>
          <strong>Workflows</strong><span className="aw-accordion-chevron" aria-hidden="true"><Icons.ChevronDown /></span>
        </button>
        <button type="button" className="aw-icon-button" title="New Local workflow" aria-label="New workflow" onClick={() => onCreate(LOCAL_OWNER.id)}><Icons.Plus /></button>
      </div>
      <div className="aw-list-sections" id={listId} hidden={collapsed}>
        {folders.map((owner) => {
          const mine = rows.filter((row) => (row.owner?.id || LOCAL_OWNER.id) === owner.id);
          const open = !closed[owner.id];
          const name = owner.kind === "team" ? owner.label : "Local";
          const bodyId = `${listId}-${owner.id}`;
          return (
            <section className={`aw-workflow-section aw-folder aw-folder--${owner.kind}`} key={owner.id} aria-label={ownerName(owner)}>
              <div className="aw-section-head">
                <button type="button" className="aw-section-toggle" aria-label={ownerName(owner)} aria-expanded={open} aria-controls={bodyId} title={ownerHelp(owner)} onClick={() => setClosed((current) => ({ ...current, [owner.id]: open }))}>
                  <span className="aw-accordion-chevron" aria-hidden="true"><Icons.ChevronDown /></span>
                  <span className="aw-folder-icon" aria-hidden="true"><OwnerIcon owner={owner} /></span>
                  <strong>{name}</strong><small>{mine.length}</small>
                </button>
                {owner.kind === "team" && owner.slug ? (
                  <button type="button" className="aw-icon-button" title={`Open ${ownerName(owner)} workflows on the web`} aria-label={`Open ${ownerName(owner)} on the web`} onClick={() => void getApi()?.workflow_open_web?.(owner.id)}><Icons.Globe /></button>
                ) : null}
                {owner.readOnly ? (
                  <span className="aw-folder-lock" role="img" aria-label={`Read-only: ${owner.reason || ""}`} title={owner.reason}><Icons.Lock /></span>
                ) : (
                  <button type="button" className="aw-icon-button" title={`New workflow in ${ownerName(owner)}`} aria-label={`New workflow in ${ownerName(owner)}`} onClick={() => onCreate(owner.id)}><Icons.Plus /></button>
                )}
              </div>
              <p className={`aw-folder-status${owner.sync?.error ? " is-error" : ""}`} title={owner.sync?.error || ownerHelp(owner)}>{folderStatus(owner, nowMs)}</p>
              <ul className="aw-list-ul" id={bodyId} hidden={!open}>
                {mine.map((row) => (
                  <li key={row.id}>
                    <button type="button" className={"aw-list-row" + (row.id === activeId ? " is-active" : "")} aria-current={row.id === activeId ? "true" : undefined} onClick={() => onOpen(row.id)}>
                      <span className="aw-list-name">{row.name || "Untitled"}</span>
                      <TriggerBadge row={row} />
                      <span className="aw-list-meta" title={row.enabled ? "Enabled" : "Disabled"}>{row.enabled ? "on" : "off"}</span>
                    </button>
                  </li>
                ))}
                {!mine.length && <li className="aw-section-empty">No workflows yet</li>}
                {owner.kind === "local" && owners.localImport ? (
                  <li className="aw-import-row">
                    <span>{owners.localImport} from when you were signed out</span>
                    <button type="button" onClick={onImportLocal}><Icons.Download /> Bring in</button>
                  </li>
                ) : null}
              </ul>
            </section>
          );
        })}
        {owners.signedIn === false ? <p className="aw-list-hint">Sign in to share workflows with a team.</p> : null}
      </div>
    </aside>
  );
}
