import { GLOBAL_PROJECT_SLUG } from "../../utils/sidebarTree";

/** True when an island or folder project is open (not the Global Agents bucket). */
export function hasOpenProject(projectSlug: string): boolean {
  const slug = (projectSlug || "").trim();
  return !!slug && slug !== GLOBAL_PROJECT_SLUG;
}

/**
 * Content lists the open project's files. With no project there is nothing to list
 * (the tree only says "No project selected."), so the section stays collapsed and the
 * rail goes to Duckies. The saved state is untouched: Content opens again as it was
 * once a project is open.
 */
export function contentCollapsedWithoutProject<T extends string>(
  collapsed: Record<T, boolean>,
  projectSlug: string,
): Record<T, boolean> {
  if (hasOpenProject(projectSlug) || !("files" in collapsed) || collapsed["files" as T]) return collapsed;
  return { ...collapsed, files: true };
}

/** Expanding Content does nothing while no project is open (it stays collapsed). */
export function canToggleStackedPanel(id: string, projectSlug: string): boolean {
  return id !== "files" || hasOpenProject(projectSlug);
}
