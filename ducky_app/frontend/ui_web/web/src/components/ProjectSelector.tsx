import { useCallback, useEffect, useRef, useState } from "react";
import { DropdownPanel } from "./DropdownPanel";
import { Icons } from "../icons/Icons";
import { TruncatedText } from "./TruncatedText";
import type { ProjectFolderInspection, ProjectInfo, RecentProject } from "../types/panel";
import { getApi, isRemote } from "../hooks/usePanelApi";
import { useOptionalEditorWorkspaceFlush } from "../contexts/EditorWorkspaceBridge";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { PROJECT_SELECTED_EVENT } from "../hooks/useProject";

interface ProjectSelectorProps {
  project: ProjectInfo;
  onProjectChanged?: () => void;
  /** Project name UEFN currently has open (the live/MCP-connected project). */
  uefnProjectName?: string;
  /** False when the live UEFN map differs from the panel's active project. */
  projectMatch?: boolean;
  /** Whether the UEFN listener is online (mismatch is only meaningful when it is). */
  listenerOnline?: boolean;
  /** Menu body only — used inside the mobile/remote connection dropdown. */
  embedded?: boolean;
}

function sameProjectName(a: string | undefined, b: string | undefined): boolean {
  return !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();
}

type ConfirmFn = ReturnType<typeof useConfirmModal>["confirm"];
type AlertFn = ReturnType<typeof useConfirmModal>["alert"];

/** Any folder can be a project. When the pick is a plain folder that holds islands
 * (e.g. "Fortnite Projects"), ask whether an island inside was meant. Returns the path
 * to open, or null to cancel. */
export async function resolvePickedFolder(
  api: { inspect_project_folder?: (path: string) => Promise<ProjectFolderInspection> },
  picked: string,
  confirm: ConfirmFn,
  alert: AlertFn,
): Promise<string | null> {
  if (typeof api.inspect_project_folder !== "function") return picked;
  let info: ProjectFolderInspection;
  try {
    info = await api.inspect_project_folder(picked);
  } catch {
    return picked;
  }
  if (!info.ok) {
    await alert({ title: "Can't open that folder", message: info.error || "Pick a different folder." });
    return null;
  }
  const path = info.path || picked;
  const islands = info.kind === "folder" ? info.islands ?? [] : [];
  if (islands.length === 1) {
    const island = islands[0]!;
    const choice = await confirm({
      title: "Open the island inside?",
      message: `"${info.name}" isn't a UEFN island, but it holds one: ${island.name}.\n\nOpen ${island.name}, or open the whole folder as a normal project?`,
      confirmLabel: `Open ${island.name}`,
      extraLabel: "Open the folder",
    });
    if (choice === true) return island.path;
    return choice === "extra" ? path : null;
  }
  if (islands.length > 1) {
    const names = islands.map((row) => row.name).join(", ");
    const ok = await confirm({
      title: "Open as a normal folder?",
      message: `"${info.name}" isn't a UEFN island, but it holds ${islands.length}: ${names}.\n\nTo work on one island, choose Add project again and pick that island's folder.`,
      confirmLabel: "Open the folder",
    });
    return ok === true ? path : null;
  }
  return path;
}

export function ProjectSelector({
  project,
  onProjectChanged,
  uefnProjectName,
  projectMatch,
  listenerOnline,
  embedded = false,
}: ProjectSelectorProps) {
  const flushFromBridge = useOptionalEditorWorkspaceFlush();
  const { confirm, alert } = useConfirmModal();
  const [isOpen, setIsOpen] = useState(false);
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const ignoreAnchorRef = useRef(false);
  const pickingRef = useRef(false);
  const switchRevisionRef = useRef(0);
  const switchChainRef = useRef(Promise.resolve());

  const close = useCallback(() => setIsOpen(false), []);

  const refreshRecent = useCallback(() => {
    const api = getApi();
    if (!api) return;
    void api.list_recent_projects().then(setRecent);
  }, []);

  const selectProject = useCallback(
    async (path: string) => {
      const api = getApi();
      if (!api) return;
      close();
      const revision = ++switchRevisionRef.current;
      // Serialize writes to the global project setting; queued clicks supersede
      // each other instead of racing and finishing on the wrong island.
      const pending = switchChainRef.current.then(async () => {
        if (revision !== switchRevisionRef.current) return;
        await flushFromBridge?.();
        if (revision !== switchRevisionRef.current) return;
        const info = await api.set_project_root(path);
        if (revision !== switchRevisionRef.current) return;
        window.dispatchEvent(new CustomEvent(PROJECT_SELECTED_EVENT, { detail: info }));
        onProjectChanged?.();
      }).catch((e: unknown) => {
        // A backend hiccup (e.g. settings save contended by another instance) must not
        // leave the dropdown stuck open with an unhandled rejection.
        console.error("[project-selector] switch failed", e);
      });
      switchChainRef.current = pending;
      await pending;
    },
    [close, flushFromBridge, onProjectChanged],
  );

  const deleteProject = useCallback(
    async (item: RecentProject) => {
      const ok = await confirm({
        title: "Remove project?",
        message: `Remove "${item.name}" from UEFN-Ducky?\n\nThis deletes chat history, editor state, and the Ducky init script from the project. The project folder on disk is not deleted.`,
        confirmLabel: "Remove",
        danger: true,
      });
      if (!ok) return;

      const api = getApi();
      if (!api) return;
      try {
        await flushFromBridge?.();
        await api.delete_recent_project(item.path);
        onProjectChanged?.();
        refreshRecent();
      } catch (e) {
        console.error("[project-selector] delete failed", e);
      }
    },
    [confirm, flushFromBridge, onProjectChanged, refreshRecent],
  );

  const addProject = useCallback(async () => {
    if (pickingRef.current) return;
    pickingRef.current = true;
    ignoreAnchorRef.current = true;
    close();
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    try {
      const api = getApi();
      if (!api) return;
      const picked = await api.pick_project_path();
      if (!picked) return;
      const path = await resolvePickedFolder(api, picked, confirm, alert);
      if (path) await selectProject(path);
    } finally {
      pickingRef.current = false;
      window.setTimeout(() => {
        ignoreAnchorRef.current = false;
      }, 600);
    }
  }, [alert, close, confirm, selectProject]);

  useEffect(() => {
    if (!isOpen && !embedded) return;
    refreshRecent();
  }, [embedded, isOpen, project.path, refreshRecent]);

  const label = project.path?.trim() ? project.name : "Select project";

  const uefnName = (uefnProjectName || "").trim();
  const hasLiveProject = !!listenerOnline && uefnName.length > 0;
  // The panel is editing one project while UEFN has a different one open — file/workspace
  // edits and the live map would target different projects. A folder project is not an
  // island, so UEFN having any island open is never a mismatch.
  const isFolderProject = project.kind === "folder";
  const mismatch =
    hasLiveProject && !isFolderProject && projectMatch === false && !sameProjectName(project.name, uefnName);
  const matchedRecent = mismatch ? recent.find((r) => sameProjectName(r.name, uefnName)) : undefined;

  const onAnchorPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (ignoreAnchorRef.current || pickingRef.current) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    setIsOpen((open) => !open);
  };

  const onAddProjectPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    void addProject();
  };

  const menu = (
    <>
        {mismatch && (
          <div className="project-selector-mismatch-banner">
            <span className="project-selector-mismatch-banner-icon" aria-hidden="true">
              <Icons.AlertTriangle />
            </span>
            <div className="project-selector-mismatch-banner-body">
              <div className="project-selector-mismatch-banner-title">
                UEFN has <strong>{uefnName}</strong> open
              </div>
              <div className="project-selector-mismatch-banner-sub">
                The panel is editing <strong>{project.name}</strong>. Switch so file edits and the
                live UEFN map are the same project.
              </div>
              {matchedRecent ? (
                <button
                  type="button"
                  className="project-selector-mismatch-switch-btn"
                  onClick={() => void selectProject(matchedRecent.path)}
                >
                  Switch panel to {uefnName}
                </button>
              ) : (
                <div className="project-selector-mismatch-hint">
                  Add {uefnName} with “Add project…” below to switch to it.
                </div>
              )}
            </div>
          </div>
        )}
        {recent.length > 0 && (
          <>
            <div className="project-selector-section-label">
              RECENT PROJECTS
            </div>
            {recent.map((item) => {
              const isActive = item.active;
              const isConnected = hasLiveProject && sameProjectName(item.name, uefnName);
              return (
                <div key={item.path} className="project-selector-item-row">
                  <button
                    type="button"
                    onClick={() => void selectProject(item.path)}
                    className={`project-selector-item-btn${isActive ? " is-active" : ""}`}
                  >
                    <span
                      className="project-selector-kind-icon"
                      title={item.kind === "folder" ? "Folder project" : "UEFN island"}
                    >
                      {item.kind === "folder" ? <Icons.Folder /> : <Icons.Verse />}
                    </span>
                    <TruncatedText
                      className="ui-flex-1-min-block"
                      title={item.path}
                    >
                      {item.name}
                    </TruncatedText>
                    {isConnected && (
                      <span
                        className="project-selector-uefn-badge"
                        title={`Open in UEFN — this is the project MCP tools are connected to`}
                      >
                        UEFN
                      </span>
                    )}
                    {isActive && (
                      <span className="project-selector-check">
                        <Icons.Check />
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="project-selector-delete-btn"
                    title={`Remove ${item.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void deleteProject(item);
                    }}
                  >
                    <Icons.Trash />
                  </button>
                </div>
              );
            })}
            <div className="project-selector-divider" />
          </>
        )}

        {isRemote() ? null : (
        <>
        <button
          type="button"
          onPointerDown={onAddProjectPointerDown}
          className="project-selector-item-btn"
        >
          <Icons.Plus />
          Add project…
        </button>
        <div className="project-selector-mismatch-hint project-selector-add-hint">
          Pick your UEFN project folder (not its Content folder), or any other folder to work on
          it as a normal project.
        </div>
        </>
        )}
    </>
  );

  if (embedded) {
    return <div className="no-drag project-selector-embedded">{menu}</div>;
  }

  return (
    <div className="no-drag project-selector-root">
      <button
        ref={anchorRef}
        type="button"
        onPointerDown={onAnchorPointerDown}
        title={
          mismatch
            ? `UEFN has ${uefnName} open — the panel is editing ${project.name}. Click to switch.`
            : project.path || "Choose UEFN project"
        }
        className={`project-selector-btn${isOpen ? " is-open" : ""}${project.path ? " has-path" : " no-path"}${mismatch ? " has-mismatch" : ""}`}
      >
        <TruncatedText
          className="project-selector-title"
          title={project.path || label}
        >
          {label}
        </TruncatedText>
        {mismatch && <span className="project-selector-mismatch-dot" aria-hidden="true" />}
      </button>

      <DropdownPanel anchorRef={anchorRef} open={isOpen} onClose={close} minWidth={280}>
        {menu}
      </DropdownPanel>
    </div>
  );
}
