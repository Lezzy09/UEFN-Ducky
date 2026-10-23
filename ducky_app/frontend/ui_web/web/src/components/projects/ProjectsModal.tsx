import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ChoiceDropdown } from "../ChoiceDropdown";
import { Modal, ModalActions } from "../Modal";
import { Icons } from "../../icons/Icons";
import { getApi } from "../../hooks/usePanelApi";
import { ProjectFlavorIcon, projectFlavorName } from "../ProjectFlavorIcon";
import type { KnownProject, KnownProjectsListing, ProjectInfo } from "../../types/panel";

export type ProjectSort = "recent" | "name";
type ProjectView = "grid" | "list";

/** Rows for one tab, searched and sorted. Opened projects come first under "recent";
 * islands found on disk but never opened follow, by name. */
export function visibleProjects(
  rows: readonly KnownProject[],
  tab: string,
  query: string,
  sort: ProjectSort,
): KnownProject[] {
  const q = query.trim().toLowerCase();
  const out = rows.filter(
    (row) => row.source === tab && (!q || row.name.toLowerCase().includes(q) || row.path.toLowerCase().includes(q)),
  );
  const byName = (a: KnownProject, b: KnownProject) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  out.sort(sort === "name" ? byName : (a, b) => (b.last_opened || 0) - (a.last_opened || 0) || byName(a, b));
  return out;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "Opened 2 hours ago" / "Opened last week" / "Opened 3 weeks ago" (unix seconds or ms). */
export function openedLabel(ts: number | undefined, now = Date.now()): string {
  if (!ts) return "Never opened in Ducky";
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const min = Math.floor((now - ms) / 60_000);
  if (min < 1) return "Opened just now";
  if (min < 60) return `Opened ${plural(min, "minute")} ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `Opened ${plural(hours, "hour")} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Opened yesterday";
  if (days < 7) return `Opened ${days} days ago`;
  if (days < 14) return "Opened last week";
  if (days < 30) return `Opened ${Math.floor(days / 7)} weeks ago`;
  if (days < 60) return "Opened last month";
  if (days < 365) return `Opened ${Math.floor(days / 30)} months ago`;
  return "Opened over a year ago";
}

function kindLabel(row: KnownProject): string {
  if (row.kind === "uefn") return "UEFN";
  return projectFlavorName(row.flavor || "folder").replace(/ project$/, "");
}

const SORT_OPTIONS = [
  { value: "recent", label: "Last opened", group: "Sort by" },
  { value: "name", label: "Name", group: "Sort by" },
];
const VIEW_OPTIONS = [
  { value: "grid", label: "Grid" },
  { value: "list", label: "List" },
];

/** The project's picture: the island's key art, else the UEFN mark, else its icon. */
function ProjectArt({ row }: { row: KnownProject }) {
  const [broken, setBroken] = useState(false);
  const thumb = !broken ? row.thumbnail_url : "";
  if (thumb) return <img className="pl-art-img" src={thumb} alt="" loading="lazy" onError={() => setBroken(true)} />;
  if (row.kind === "uefn") {
    // No key art (or it failed to load): the UEFN mark instead of a blank tile.
    return (
      <span className="pl-art-mark" aria-label="UEFN island">
        UEFN
      </span>
    );
  }
  return (
    <span className="pl-art-icon">
      <ProjectFlavorIcon flavor={row.flavor || row.kind} />
    </span>
  );
}

interface ProjectsModalProps {
  open: boolean;
  onClose: () => void;
  project: ProjectInfo;
  onOpenProject: (path: string) => void;
  onAddProject: () => void;
  onRemoveProject: (row: KnownProject) => Promise<boolean>;
  isLive: (row: { name?: string; mount?: string }) => boolean;
  /** Banner above the cards (UEFN has another island open). */
  banner?: ReactNode;
}

/** Every project Ducky knows, like a launcher: UEFN islands (found on disk, no adding
 * needed), other folders, and a tab per plugin that lists projects. Click a project to
 * see what Ducky knows about it; Open (or a double-click) switches to it. */
export function ProjectsModal({
  open,
  onClose,
  project,
  onOpenProject,
  onAddProject,
  onRemoveProject,
  isLive,
  banner,
}: ProjectsModalProps) {
  const [listing, setListing] = useState<KnownProjectsListing>({ sources: [], projects: [] });
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<ProjectSort>("recent");
  const [view, setView] = useState<ProjectView>("grid");
  const [selected, setSelected] = useState("");

  const load = useCallback(async (rescan: boolean) => {
    const api = getApi();
    if (!api?.list_known_projects) return;
    setLoading(true);
    try {
      setListing(await api.list_known_projects(rescan));
    } catch (e) {
      console.error("[projects] list failed", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    // Start on the open project's tab, with it selected.
    setTab(project.kind === "folder" ? "other" : "uefn");
    setSelected(project.path || "");
    void load(true);
  }, [open, load, project.kind, project.path]);

  const rows = useMemo(() => visibleProjects(listing.projects, tab, query, sort), [listing.projects, tab, query, sort]);
  const sources = listing.sources.length ? listing.sources : [{ id: "uefn", label: "UEFN" }, { id: "other", label: "Other" }];
  const picked = listing.projects.find((row) => row.path === selected) || null;

  const remove = async (row: KnownProject) => {
    if (!(await onRemoveProject(row))) return;
    if (selected === row.path) setSelected("");
    void load(false);
  };

  const menu = (row: KnownProject) => (
    // The menu sits on the card: its clicks never select or open the card.
    <span className="pl-card-menu" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      <ChoiceDropdown
        aria-label={`${row.name} actions`}
        size="compact"
        value=""
        minWidth={170}
        hideChevron
        trigger={<Icons.MoreHorizontal />}
        triggerClassName="pl-icon-btn"
        options={[
          { value: "open", label: "Open" },
          { value: "reveal", label: "Show in Explorer" },
          { value: "remove", label: "Remove from Ducky" },
        ]}
        onChange={(action) => {
          if (action === "open") onOpenProject(row.path);
          else if (action === "reveal") void getApi()?.open_path_in_explorer?.(row.path);
          else if (action === "remove") void remove(row);
        }}
      />
    </span>
  );

  const card = (row: KnownProject) => (
    <div
      key={row.path}
      role="option"
      tabIndex={0}
      aria-selected={row.path === selected}
      className={`pl-card${row.path === selected ? " is-selected" : ""}`}
      title={row.path}
      onClick={() => setSelected(row.path)}
      onDoubleClick={() => onOpenProject(row.path)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpenProject(row.path);
        else if (e.key === " ") {
          e.preventDefault();
          setSelected(row.path);
        }
      }}
    >
      <span className="pl-art">
        <ProjectArt row={row} />
        {isLive(row) ? <span className="pl-live">Open in UEFN</span> : null}
      </span>
      <span className="pl-card-meta">
        <span className="pl-card-kind">{kindLabel(row)}</span>
        <span className="pl-card-name">{row.name}</span>
        <span className="pl-card-opened">{openedLabel(row.last_opened)}</span>
      </span>
      {menu(row)}
    </div>
  );

  const total = listing.projects.filter((r) => r.source === tab).length;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Projects"
      width={1180}
      hideHeader
      hideClose
      className="pl-modal"
      bodyClassName="pl-body"
    >
      <div className="pl-toolbar">
        <label className="pl-search">
          <Icons.Search />
          <input
            type="text"
            placeholder="Search projects"
            aria-label="Search projects"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </label>
        <span className="pl-toolbar-sep" aria-hidden />
        <ChoiceDropdown
          aria-label="View"
          size="compact"
          value={view}
          minWidth={140}
          hideChevron
          trigger={view === "list" ? <Icons.List /> : <Icons.Grid />}
          triggerClassName="pl-round"
          options={VIEW_OPTIONS}
          onChange={(value) => setView(value as ProjectView)}
        />
        <ChoiceDropdown
          aria-label="Filter and sort"
          size="compact"
          value={sort}
          minWidth={180}
          hideChevron
          trigger={<Icons.Filter />}
          triggerClassName="pl-round"
          options={SORT_OPTIONS}
          onChange={(value) => setSort(value as ProjectSort)}
        />
        <button type="button" className="pl-round" onClick={onClose} aria-label="Close" title="Close">
          <Icons.Close />
        </button>
      </div>

      <div className="pl-heading">
        <div className="pl-tabs" role="tablist" aria-label="Project kinds">
          {sources.map((source) => (
            <button
              key={source.id}
              type="button"
              role="tab"
              aria-selected={tab === source.id}
              className={`pl-tab${tab === source.id ? " is-active" : ""}`}
              onClick={() => setTab(source.id)}
            >
              {source.id === "uefn" ? "UEFN projects" : source.id === "other" ? "Other projects" : source.label}
            </button>
          ))}
          <span className="pl-count">{plural(total, "project")}</span>
        </div>
        <button type="button" className="settings-btn pl-add-btn" onClick={onAddProject}>
          <Icons.Plus />
          Add project
        </button>
      </div>

      {banner}

      <div className={`pl-scroll pl-scroll--${view}`} role="listbox" aria-label="Projects">
        {loading && !listing.projects.length ? <div className="pl-empty">Loading projects…</div> : null}
        {rows.length ? <div className={view === "grid" ? "pl-grid" : "pl-list"}>{rows.map(card)}</div> : null}
        {!loading && !rows.length ? (
          <div className="pl-empty">
            {query
              ? "No project matches that search."
              : tab === "uefn"
                ? "No UEFN islands in Documents/Fortnite Projects yet."
                : "Add any folder to work on it as a project."}
          </div>
        ) : null}
      </div>

      <div className="pl-details">
        {picked ? (
          <>
            <span className="pl-details-art">
              <ProjectArt row={picked} />
            </span>
            <div className="pl-details-main">
              <div className="pl-details-name">{picked.name}</div>
              <div className="pl-details-path" title={picked.path}>{picked.path}</div>
            </div>
            <dl className="pl-facts">
              <div>
                <dt>Type</dt>
                <dd>{picked.kind === "uefn" ? "UEFN island" : projectFlavorName(picked.flavor || "folder")}</dd>
              </div>
              <div>
                <dt>Last opened</dt>
                <dd>{openedLabel(picked.last_opened).replace(/^Opened /, "")}</dd>
              </div>
              <div>
                <dt>Listener</dt>
                <dd className={picked.listener_ready ? "is-ok" : ""}>
                  {picked.kind !== "uefn" ? "Not needed" : picked.listener_ready ? "Ready" : "Sets up at next start"}
                </dd>
              </div>
              {isLive(picked) ? (
                <div>
                  <dt>UEFN</dt>
                  <dd className="is-ok">Open now</dd>
                </div>
              ) : null}
            </dl>
          </>
        ) : (
          <div className="pl-details-hint">Select a project to see what Ducky knows about it.</div>
        )}
        <ModalActions
          onCancel={onClose}
          onConfirm={() => picked && onOpenProject(picked.path)}
          confirmLabel={picked?.active ? "Open (current)" : "Open"}
          confirmDisabled={!picked}
        />
      </div>
    </Modal>
  );
}
