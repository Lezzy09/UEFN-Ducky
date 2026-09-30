import { useEffect, useRef, useState, type DragEvent, type Ref } from "react";
import { getApi } from "../hooks/usePanelApi";
import type { AutomationSummaryDto, PluginScopeStatus, WorkflowOwnerDto, WorkflowOwnersDto } from "../types/panel";
import { Icons } from "../icons/Icons";
import { syncText } from "../plugin-ui/scopeBarText";
import { buildFolderTree, folderName, isInside, joinFolder, normalizeFolder, parentFolder, type FolderNode } from "./workflowFolders";

export const LOCAL_OWNER: WorkflowOwnerDto = { id: "local", kind: "local", label: "Local" };

export function ownerName(owner: WorkflowOwnerDto | undefined): string {
  return owner?.kind === "team" ? `Team · ${owner.label}` : "Local";
}

export function OwnerIcon({ owner }: { owner: WorkflowOwnerDto | undefined }) {
  return owner?.kind === "team" ? <Icons.Users /> : <Icons.Monitor />;
}

/** Who can see it, in words (tooltips on the folder and the toolbar chip). */
export function ownerHelp(owner: WorkflowOwnerDto | undefined): string {
  if (owner?.kind !== "team") return "Local workflows stay with your account on this PC.";
  const who = `Team ${owner.label}: every member sees it and changes sync to the team.`;
  return owner.readOnly && owner.reason ? `${who} ${owner.reason}` : who;
}

/** The folder's second line. Local has none; a team line is where its copy stands. */
export function folderStatus(owner: WorkflowOwnerDto, nowMs: number): string {
  if (owner.kind !== "team") return "";
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
  const title = trigger.kind === "function" ? "Reusable: other workflows run it with a Run workflow node" : `Starts from: ${trigger.label}${here}`;
  return (
    <span className={`aw-trigger aw-trigger--${trigger.kind}${teamRun && !row.run_here ? " is-elsewhere" : ""}`} title={title}>
      {trigger.label}
    </span>
  );
}

type Drag = { kind: "workflow"; id: string; owner: string; folder: string } | { kind: "folder"; path: string; owner: string };
type Editing = { owner: string; path: string; mode: "new" | "rename" };

type Props = {
  listId: string;
  listRef: Ref<HTMLElement>;
  owners: WorkflowOwnersDto;
  rows: AutomationSummaryDto[];
  activeId: string;
  collapsed: boolean;
  nowMs: number;
  /** Folders made on this PC that hold nothing yet, per owner id. */
  emptyFolders?: Record<string, string[]>;
  onToggleCollapsed: () => void;
  onOpen: (id: string) => void;
  onCreate: (ownerId: string, folder?: string) => void;
  onImportLocal: () => void;
  onAddFolder?: (ownerId: string, path: string) => void;
  onMoveWorkflow?: (id: string, ownerId: string, folder: string) => void;
  /** Rename or move a folder; moving it into its parent removes it and keeps the workflows. */
  onMoveFolder?: (ownerId: string, path: string, newPath: string) => void;
};

/** Workflows sidebar: one section per owner (Local, then each team), with folders
 *  inside. Drag a workflow or a folder onto a folder, or onto the owner, to file it. */
export function WorkflowList({ listId, listRef, owners, rows, activeId, collapsed, nowMs, emptyFolders = {}, onToggleCollapsed, onOpen, onCreate, onImportLocal, onAddFolder, onMoveWorkflow, onMoveFolder }: Props) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<Editing | null>(null);
  const [dropAt, setDropAt] = useState("");
  const drag = useRef<Drag | null>(null);
  const sections = owners.owners?.length ? owners.owners : [LOCAL_OWNER];
  const canFile = !!onMoveWorkflow;

  const canDrop = (owner: WorkflowOwnerDto, path: string) => {
    const moving = drag.current;
    if (!moving || owner.readOnly || moving.owner !== owner.id) return false;
    if (moving.kind === "workflow") return moving.folder !== path;
    return !isInside(path, moving.path) && parentFolder(moving.path) !== path;
  };
  const dropProps = (owner: WorkflowOwnerDto, path: string) => {
    const key = `${owner.id}:${path}`;
    return {
      onDragOver: (event: DragEvent) => {
        if (!canDrop(owner, path)) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "move";
        if (dropAt !== key) setDropAt(key);
      },
      onDragLeave: (event: DragEvent) => {
        if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) && dropAt === key) setDropAt("");
      },
      onDrop: (event: DragEvent) => {
        const moving = drag.current;
        setDropAt("");
        if (!moving || !canDrop(owner, path)) return;
        event.preventDefault();
        event.stopPropagation();
        drag.current = null;
        if (moving.kind === "workflow") onMoveWorkflow?.(moving.id, owner.id, path);
        else onMoveFolder?.(owner.id, moving.path, joinFolder(path, folderName(moving.path)));
      },
    };
  };
  const startDrag = (event: DragEvent, value: Drag) => {
    drag.current = value;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", value.kind === "workflow" ? value.id : value.path);
  };
  const endDrag = () => { drag.current = null; setDropAt(""); };

  const commitName = (owner: WorkflowOwnerDto, name: string) => {
    const edit = editing;
    setEditing(null);
    const clean = normalizeFolder(name).replace(/\//g, " ");
    if (!edit || !clean) return;
    if (edit.mode === "new") onAddFolder?.(owner.id, joinFolder(edit.path, clean));
    else if (clean !== folderName(edit.path)) onMoveFolder?.(owner.id, edit.path, joinFolder(parentFolder(edit.path), clean));
  };

  const renderRows = (owner: WorkflowOwnerDto, list: AutomationSummaryDto[], depth: number) => list.map((row) => (
    <li key={row.id}>
      <button type="button" className={"aw-list-row" + (row.id === activeId ? " is-active" : "")} aria-current={row.id === activeId ? "true" : undefined}
        style={{ paddingLeft: 8 + depth * 14 }} draggable={canFile && !owner.readOnly}
        onDragStart={(event) => startDrag(event, { kind: "workflow", id: row.id, owner: owner.id, folder: normalizeFolder(row.folder) })} onDragEnd={endDrag}
        onClick={() => onOpen(row.id)}>
        <span className="aw-list-name">{row.name || "Untitled"}</span>
        <TriggerBadge row={row} />
        <span className="aw-list-meta" title={row.enabled ? "Enabled" : "Disabled"}>{row.enabled ? "on" : "off"}</span>
      </button>
    </li>
  ));

  const newFolderRow = (owner: WorkflowOwnerDto, parent: string, depth: number) => editing?.mode === "new" && editing.owner === owner.id && editing.path === parent ? (
    <li className="aw-tree-folder aw-tree-folder--editing" style={{ paddingLeft: 8 + depth * 14 }}>
      <span className="aw-folder-icon" aria-hidden="true"><Icons.Folder /></span>
      <FolderNameInput label="New folder name" initial="" onDone={(name) => commitName(owner, name)} onCancel={() => setEditing(null)} />
    </li>
  ) : null;

  const renderFolder = (owner: WorkflowOwnerDto, folder: FolderNode, depth: number) => {
    const key = `${owner.id}:${folder.path}`;
    const open = !closed[key];
    const renaming = editing?.mode === "rename" && editing.owner === owner.id && editing.path === folder.path;
    const bodyId = `${listId}-${owner.id}-f-${folder.path}`;
    return (
      <li key={folder.path} className="aw-tree-item">
        <div className={`aw-tree-folder${dropAt === key ? " is-drop-target" : ""}`} style={{ paddingLeft: 4 + depth * 14 }} {...dropProps(owner, folder.path)}
          draggable={canFile && !owner.readOnly && !renaming} onDragStart={(event) => startDrag(event, { kind: "folder", path: folder.path, owner: owner.id })} onDragEnd={endDrag}>
          {renaming ? (
            <>
              <span className="aw-folder-icon" aria-hidden="true"><Icons.Folder /></span>
              <FolderNameInput label="Folder name" initial={folder.name} onDone={(name) => commitName(owner, name)} onCancel={() => setEditing(null)} />
            </>
          ) : (
            <button type="button" className="aw-tree-toggle" aria-expanded={open} aria-controls={bodyId} aria-label={`Folder ${folder.name}`} title={folder.path}
              onClick={() => setClosed((current) => ({ ...current, [key]: open }))}>
              <span className="aw-accordion-chevron" aria-hidden="true"><Icons.ChevronDown /></span>
              <span className="aw-folder-icon" aria-hidden="true"><Icons.Folder /></span>
              <span className="aw-list-name">{folder.name}</span><small>{folder.count}</small>
            </button>
          )}
          {!owner.readOnly && !renaming ? (
            <span className="aw-tree-actions">
              <button type="button" className="aw-icon-button" title={`New workflow in ${folder.name}`} aria-label={`New workflow in ${folder.name}`} onClick={() => onCreate(owner.id, folder.path)}><Icons.Plus /></button>
              {onAddFolder ? <button type="button" className="aw-icon-button" title="New folder inside" aria-label={`New folder in ${folder.name}`} onClick={() => { setClosed((current) => ({ ...current, [key]: false })); setEditing({ owner: owner.id, path: folder.path, mode: "new" }); }}><Icons.FolderPlus /></button> : null}
              {onMoveFolder ? <button type="button" className="aw-icon-button" title="Rename folder" aria-label={`Rename ${folder.name}`} onClick={() => setEditing({ owner: owner.id, path: folder.path, mode: "rename" })}><Icons.Pencil /></button> : null}
              {onMoveFolder ? <button type="button" className="aw-icon-button" title="Remove folder (its workflows move up a level)" aria-label={`Remove folder ${folder.name}`} onClick={() => onMoveFolder(owner.id, folder.path, parentFolder(folder.path))}><Icons.Trash /></button> : null}
            </span>
          ) : null}
        </div>
        <ul className="aw-list-ul aw-tree-children" id={bodyId} hidden={!open}>
          {newFolderRow(owner, folder.path, depth + 1)}
          {folder.folders.map((child) => renderFolder(owner, child, depth + 1))}
          {renderRows(owner, folder.rows, depth + 1)}
          {!folder.count && !folder.folders.length ? <li className="aw-section-empty" style={{ paddingLeft: 8 + (depth + 1) * 14 }}>Empty. Drag workflows here.</li> : null}
        </ul>
      </li>
    );
  };

  return (
    <aside className="aw-list" ref={listRef} aria-label="Workflows">
      <div className="aw-list-head">
        <button type="button" className="aw-list-toggle" title={collapsed ? "Expand Workflows" : "Collapse Workflows"} aria-expanded={!collapsed} aria-controls={listId} onClick={onToggleCollapsed}>
          <strong>Workflows</strong><span className="aw-accordion-chevron" aria-hidden="true"><Icons.ChevronDown /></span>
        </button>
        <button type="button" className="aw-icon-button" title="New Local workflow" aria-label="New workflow" onClick={() => onCreate(LOCAL_OWNER.id)}><Icons.Plus /></button>
      </div>
      <div className="aw-list-sections" id={listId} hidden={collapsed}>
        {sections.map((owner) => {
          const mine = rows.filter((row) => (row.owner?.id || LOCAL_OWNER.id) === owner.id);
          const tree = buildFolderTree(mine, emptyFolders[owner.id] || []);
          const open = !closed[owner.id];
          const name = owner.kind === "team" ? owner.label : "Local";
          const bodyId = `${listId}-${owner.id}`;
          const rootKey = `${owner.id}:`;
          return (
            <section className={`aw-workflow-section aw-folder aw-folder--${owner.kind}`} key={owner.id} aria-label={ownerName(owner)}>
              <div className={`aw-section-head${dropAt === rootKey ? " is-drop-target" : ""}`} {...dropProps(owner, "")}>
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
                  <>
                    {onAddFolder ? <button type="button" className="aw-icon-button" title={`New folder in ${ownerName(owner)}`} aria-label={`New folder in ${ownerName(owner)}`} onClick={() => { setClosed((current) => ({ ...current, [owner.id]: false })); setEditing({ owner: owner.id, path: "", mode: "new" }); }}><Icons.FolderPlus /></button> : null}
                    <button type="button" className="aw-icon-button" title={`New workflow in ${ownerName(owner)}`} aria-label={`New workflow in ${ownerName(owner)}`} onClick={() => onCreate(owner.id)}><Icons.Plus /></button>
                  </>
                )}
              </div>
              {folderStatus(owner, nowMs) ? (
                <p className={`aw-folder-status${owner.sync?.error ? " is-error" : ""}`} title={owner.sync?.error || ownerHelp(owner)}>{folderStatus(owner, nowMs)}</p>
              ) : null}
              <ul className="aw-list-ul" id={bodyId} hidden={!open}>
                {newFolderRow(owner, "", 0)}
                {tree.folders.map((folder) => renderFolder(owner, folder, 0))}
                {renderRows(owner, tree.rows, 0)}
                {!mine.length && !tree.folders.length && !(editing?.owner === owner.id) && <li className="aw-section-empty">No workflows yet</li>}
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

/** Enter or blur saves, Escape cancels. */
function FolderNameInput({ label, initial, onDone, onCancel }: { label: string; initial: string; onDone: (name: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(initial);
  const input = useRef<HTMLInputElement>(null);
  const finished = useRef(false);
  useEffect(() => { input.current?.focus({ preventScroll: true }); input.current?.select(); }, []);
  const finish = (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    if (save) onDone(text); else onCancel();
  };
  return <input ref={input} className="aw-tree-input" aria-label={label} value={text} placeholder="Folder name" maxLength={64}
    onChange={(event) => setText(event.target.value)} onBlur={() => finish(true)}
    onKeyDown={(event) => {
      event.stopPropagation();
      if (event.nativeEvent.isComposing) return;
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      else if (event.key === "Escape") { event.preventDefault(); finish(false); }
    }} />;
}
