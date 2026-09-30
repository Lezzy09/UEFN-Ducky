import type { AutomationRunDto, AutomationRunStepDto } from "../types/panel";

export function formatRunLog(run: AutomationRunDto | null, name?: string): string {
  if (!run) return "";
  const lines: string[] = [];
  if (name) lines.push(name);
  if (run.ok === false) lines.push(run.error ? `Failed: ${run.error}` : "Failed");
  else if (run.ok) lines.push("Finished");
  const steps = run.steps || [];
  const add = (list: AutomationRunStepDto[], prefix: string) => list.forEach((s, i) => {
    const label = s.label || s.type || `step ${i + 1}`;
    const number = `${prefix}${i + 1}`;
    lines.push(s.ok === false ? `${number}. ${label} — ${s.error || "error"}` : `${number}. ${label} ok`);
    if (s.substeps?.length) add(s.substeps, `${number}.`);  // steps of the workflow a Run workflow node ran
  });
  add(steps, "");
  const outputs = Object.entries(run.outputs || {});
  if (outputs.length) lines.push(`Returned: ${outputs.map(([key, value]) => `${key} = ${typeof value === "string" ? value : JSON.stringify(value)}`).join(", ")}`);
  if (!steps.length && run.error && run.ok !== false) lines.push(run.error);
  return lines.join("\n");
}

export function runLogHasContent(run: AutomationRunDto | null): boolean {
  return Boolean(run && ((run.steps && run.steps.length) || run.error || run.ok === false));
}
