import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { ChoiceDropdown } from "../ChoiceDropdown";
import { Modal } from "../Modal";
import { Icons } from "../../icons/Icons";
import { getApi } from "../../hooks/usePanelApi";
import { formatRelativeTime } from "../../utils/formatRelativeTime";
import { ProjectFlavorIcon, projectFlavorName } from "../ProjectFlavorIcon";
import type { KnownProject, KnownProjectsListing, ProjectInfo } from "../../types/panel";

export type ProjectSort = "recent" | "name";

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

function kindLabel(row: KnownProject): string {
  if (row.kind === "uefn") return "UEFN";
  return projectFlavorName(row.flavor || "folder").replace(/ project$/, "");
}

const SORT_OPTIONS = [
  { value: "recent", label: "Last opened" },
  { value: "name", label: "Name" },
];

const CloseIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const Check = () => (
  <span className="vtm-card-check" aria-hidden>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  </span>
);

/** The card's picture: the island's key art, else the UEFN mark, else the project's icon. */
function CardArt({ row, active }: { row: KnownProject; active: boolean }) {
  const [broken, setBroken] = useState(false);
  const thumb = !broken ? row.thumbnail_url : "";
  return (
    <span className={`vtm-card-icon${active ? " is-selected" : ""}${row.kind === "uefn" && !thumb ? " vtm-card-icon--uefn" : ""}`} aria-hidden={!!thumb}>
      {thumb ? (
        <img src={thumb} alt="" loading="lazy" onError={() => setBroken(true)} />
      ) : row.kind === "uefn" ? (
        // No key art (or it failed to load): the UEFN mark instead of a blank tile.
        <span aria-label="UEFN island">UEFN</span>
      ) : (
        <ProjectFlavorIcon flavor={row.flavor || row.kind} />
      )}
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

/** Every project Ducky knows, in the same picker as New workflow: UEFN islands (found on
 * disk, no adding needed), other folders, and a shelf per plugin that lists projects. */
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
    // Start on the open project's shelf: an island opens on UEFN, a repo on Other.
    setTab(project.kind === "folder" ? "other" : "uefn");
    void load(true);
  }, [open, load, project.kind]);

  const rows = useMemo(() => visibleProjects(listing.projects, tab, query, sort), [listing.projects, tab, query, sort]);
  const sources = listing.sources.length ? listing.sources : [{ id: "uefn", label: "UEFN" }, { id: "other", label: "Other" }];

  const remove = async (row: KnownProject, e: MouseEvent) => {
    e.stopPropagation();
    if (await onRemoveProject(row)) void load(false);
  };

  const card = (row: KnownProject) => {
    const opened = formatRelativeTime(row.last_opened);
    return (
      <button
        key={row.path}
        type="button"
        role="option"
        aria-selected={row.active}
        className={`vtm-card${row.active ? " is-selected" : ""}`}
        title={row.path}
        onClick={() => onOpenProject(row.path)}
      >
        <CardArt row={row} active={row.active} />
        <span className="vtm-card-body">
          <span className="vtm-card-name">{row.name}</span>
          <span className="vtm-card-desc">{opened ? `Opened ${opened}` : "Never opened in Ducky"}</span>
          <span className={`vtm-badge${isLive(row) ? " vtm-badge--system" : ""}`}>
            {isLive(row) ? `${kindLabel(row)} · Open in UEFN` : kindLabel(row)}
          </span>
        </span>
        {row.active ? <Check /> : null}
        <span className="vtm-card-actions">
          <span
            role="button"
            tabIndex={0}
            className="vtm-card-action vtm-card-action--danger"
            aria-label={`Remove ${row.name}`}
            title={`Remove ${row.name}`}
            onClick={(e) => void remove(row, e)}
          >
            <Icons.Trash />
          </span>
        </span>
      </button>
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Projects"
      width={820}
      hideHeader
      hideClose
      className="vtm-modal vtm-modal--workflows"
      bodyClassName="vtm-modal-body"
    >
      <div className="vtm vtm--workflows">
        <div className="vtm-view vtm-view--active">
          <div className="vtm-header">
            <div className="vtm-header-left">
              <h2 className="vtm-title">Projects</h2>
              <ChoiceDropdown
                aria-label="Sort projects"
                size="compact"
                value={sort}
                minWidth={160}
                options={SORT_OPTIONS}
                onChange={(value) => setSort(value as ProjectSort)}
              />
            </div>
            <button type="button" className="vtm-icon-btn" onClick={onClose} aria-label="Close"><CloseIcon /></button>
          </div>
          <div className="vtm-search">
            <div className="vtm-search-wrap">
              <span className="vtm-search-icon" aria-hidden>
                <svg className="vtm-search-svg" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </span>
              <input
                type="text"
                className="vtm-input vtm-search-input"
                placeholder="Search projects..."
                aria-label="Search projects"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
            </div>
            <div className="vtm-shelves" role="tablist" aria-label="Project kinds">
              {sources.map((source) => (
                <button
                  key={source.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === source.id}
                  className={`vtm-shelf${tab === source.id ? " is-active" : ""}`}
                  onClick={() => setTab(source.id)}
                >
                  {source.label}
                  <span className="vtm-shelf-count">{listing.projects.filter((r) => r.source === source.id).length}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="vtm-body vtm-picker-body" role="listbox" aria-label="Projects">
            {banner}
            {loading && !listing.projects.length ? <div className="vtm-status">Loading projects…</div> : null}
            {rows.length ? <div className="vtm-grid">{rows.map(card)}</div> : null}
            {!loading && !rows.length ? (
              <div className="vtm-empty">
                <div className="vtm-empty-icon" aria-hidden>🔍</div>
                <p className="vtm-empty-text">
                  {query
                    ? "No matching projects"
                    : tab === "uefn"
                      ? "No UEFN islands in Documents/Fortnite Projects yet"
                      : "Add any folder to work on it as a project"}
                </p>
              </div>
            ) : null}
          </div>
          <div className="vtm-footer">
            <button type="button" className="vtm-btn vtm-btn--ghost" onClick={onClose}>Close</button>
            <button type="button" className="vtm-btn vtm-btn--primary" onClick={onAddProject}>
              <Icons.Plus />
              Add project
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
