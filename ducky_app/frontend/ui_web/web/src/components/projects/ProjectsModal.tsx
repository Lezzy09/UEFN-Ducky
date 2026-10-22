import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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

interface ProjectCardProps {
  row: KnownProject;
  live: boolean;
  onOpen: (row: KnownProject) => void;
  onRemove: (row: KnownProject) => void;
}

function ProjectCard({ row, live, onOpen, onRemove }: ProjectCardProps) {
  const [broken, setBroken] = useState(false);
  const thumb = !broken ? row.thumbnail_url : "";
  const opened = formatRelativeTime(row.last_opened);
  return (
    <div className={`projects-card${row.active ? " is-active" : ""}`}>
      <button type="button" className="projects-card-open" title={row.path} onClick={() => onOpen(row)}>
        <span className="projects-card-thumb">
          {thumb ? (
            <img src={thumb} alt="" loading="lazy" onError={() => setBroken(true)} />
          ) : (
            <span className="projects-card-thumb-icon">
              <ProjectFlavorIcon flavor={row.flavor || row.kind} />
            </span>
          )}
        </span>
        <span className="projects-card-kind">
          {kindLabel(row)}
          {live ? <span className="project-selector-uefn-badge">Open in UEFN</span> : null}
        </span>
        <span className="projects-card-name">{row.name}</span>
        <span className="projects-card-meta">{opened ? `Opened ${opened}` : "Never opened in Ducky"}</span>
      </button>
      <button
        type="button"
        className="project-selector-delete-btn projects-card-remove"
        title={`Remove ${row.name}`}
        onClick={() => onRemove(row)}
      >
        <Icons.Trash />
      </button>
    </div>
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
  /** Banner above the grid (UEFN has another island open). */
  banner?: ReactNode;
}

/** Every project Ducky knows, like a launcher: UEFN islands (found on disk, no adding
 * needed), other folders, and a tab per plugin that lists projects. */
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
  const [tab, setTab] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<ProjectSort>("recent");

  const load = useCallback(async (rescan: boolean) => {
    const api = getApi();
    if (!api?.list_known_projects) return;
    try {
      setListing(await api.list_known_projects(rescan));
    } catch (e) {
      console.error("[projects] list failed", e);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    // Start on the open project's tab: an island opens on UEFN, a repo on Other.
    setTab(project.kind === "folder" ? "other" : "uefn");
    void load(true);
  }, [open, load, project.kind]);

  const rows = useMemo(() => visibleProjects(listing.projects, tab, query, sort), [listing.projects, tab, query, sort]);
  const countFor = (id: string) => listing.projects.filter((r) => r.source === id).length;
  const sources = listing.sources.length ? listing.sources : [{ id: "uefn", label: "UEFN" }, { id: "other", label: "Other" }];

  const remove = async (row: KnownProject) => {
    if (await onRemoveProject(row)) void load(false);
  };

  return (
    <Modal open={open} onClose={onClose} title="Projects" width={980} className="projects-modal" bodyClassName="projects-modal-body">
      <div className="projects-toolbar">
        <div className="projects-tabs" role="tablist">
          {sources.map((source) => (
            <button
              key={source.id}
              type="button"
              role="tab"
              aria-selected={tab === source.id}
              className={`projects-tab${tab === source.id ? " is-active" : ""}`}
              onClick={() => setTab(source.id)}
            >
              {source.label}
              <span className="projects-tab-count">{countFor(source.id)}</span>
            </button>
          ))}
        </div>
        <label className="projects-search">
          <Icons.Search />
          <input
            type="search"
            placeholder="Search projects"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search projects"
          />
        </label>
        <select
          className="projects-sort"
          value={sort}
          onChange={(e) => setSort(e.target.value as ProjectSort)}
          aria-label="Sort projects"
        >
          <option value="recent">Last opened</option>
          <option value="name">Name</option>
        </select>
        <button type="button" className="settings-btn projects-add-btn" onClick={onAddProject}>
          <Icons.Plus />
          Add project
        </button>
      </div>
      {banner}
      {rows.length ? (
        <div className="projects-grid">
          {rows.map((row) => (
            <ProjectCard key={row.path} row={row} live={isLive(row)} onOpen={(r) => onOpenProject(r.path)} onRemove={remove} />
          ))}
        </div>
      ) : (
        <div className="projects-empty">
          {query
            ? "No project matches that search."
            : tab === "uefn"
              ? "No UEFN islands found in Documents/Fortnite Projects yet."
              : "Add any folder to work on it as a project."}
        </div>
      )}
    </Modal>
  );
}
