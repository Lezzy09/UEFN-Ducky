import { useCallback, useEffect, useRef, useState } from "react";
import { ChoiceDropdown, type ChoiceOption } from "../components/ChoiceDropdown";
import { getApi } from "../hooks/usePanelApi";
import type { RecentProject } from "../types/panel";

/** Select a workflow target without changing the panel's active project. */
export function ProjectField({ value, onChange, label = "UEFN project", id }: { value: string; onChange: (path: string) => void; label?: string; id?: string }) {
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

  const options: ChoiceOption[] = [
    { value: "", label: "Current project (at run time)" },
    ...projects.map((project) => ({ value: project.path, label: (project.name || project.path) + (project.active ? " (current)" : ""), hint: project.path })),
  ];
  if (value && !projects.some((project) => project.path === value)) options.push({ value, label: "Saved project — " + value });
  return <ChoiceDropdown id={id} aria-label={label} value={value} options={options} onChange={onChange} onOpen={() => void refresh()} searchable searchPlaceholder="Search projects" showSelectedHint={false} size="compact" footer={status === "loading" ? "Loading projects…" : status === "error" ? "Could not load projects — reopen to retry" : !projects.length ? "No saved projects — add one in Ducky’s project menu" : undefined} />;
}
