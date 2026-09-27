import { useCallback, useEffect, useRef, useState } from "react";
import { getApi } from "../hooks/usePanelApi";
import type { RecentProject } from "../types/panel";

/** Select a workflow target without changing the panel's active project. */
export function ProjectField({ value, onChange }: { value: string; onChange: (path: string) => void }) {
  const [projects, setProjects] = useState<RecentProject[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const request = useRef(0);
  const refresh = useCallback(async () => {
    const revision = ++request.current;
    try {
      const rows = await getApi()?.list_recent_projects?.();
      if (revision !== request.current) return;
      if (!Array.isArray(rows)) throw new Error("Project list unavailable");
      setProjects(rows.filter((project) => !!project.path));
      setStatus("ready");
    } catch {
      if (revision === request.current) setStatus("error");
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => { request.current++; };
  }, [refresh]);

  return (
    <>
      <select value={value} onChange={(event) => onChange(event.target.value)} onFocus={() => void refresh()} title={value || "Use the active project when this workflow runs"}>
        <option value="">Current project (at run time)</option>
        {projects.map((project) => (
          <option key={project.path} value={project.path} title={project.path}>
            {project.name || project.path}{project.active ? " (current)" : ""}
            {projects.some((other) => other.path !== project.path && other.name === project.name) ? ` — ${project.path}` : ""}
          </option>
        ))}
        {value && !projects.some((project) => project.path === value) ? <option value={value}>Saved project — {value}</option> : null}
        {status === "loading" ? <option disabled>Loading projects…</option> : null}
        {status === "error" ? <option disabled>Could not load projects — reopen to retry</option> : null}
        {status === "ready" && !projects.length ? <option disabled>No saved projects — add one in Ducky’s project menu</option> : null}
      </select>
    </>
  );
}
