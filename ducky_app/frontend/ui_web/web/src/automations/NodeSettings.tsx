import { useEffect, useId, useState } from "react";
import { ChoiceDropdown } from "../components/ChoiceDropdown";
import { getApi } from "../hooks/usePanelApi";
import type { AutomationFieldDto, AutomationGraphNodeDto, AutomationNodeDto } from "../types/panel";
import { AgentField } from "./AgentField";
import { ProjectField } from "./ProjectField";
import { ToolSettings } from "./ToolSettings";

export function hasNodeSettings(node: AutomationGraphNodeDto, meta?: AutomationNodeDto) {
  return node.type === "tool.call" || !!meta?.config_fields?.length;
}

export function NodeSettings({ node, meta, onChange }: { node: AutomationGraphNodeDto; meta?: AutomationNodeDto; onChange: (node: AutomationGraphNodeDto) => void }) {
  return <div className="aw-insp-form">
    {node.type === "tool.call" ? <ToolSettings node={node} onChange={onChange} /> : (meta?.config_fields || []).map((field) => <NodeField key={field.id} field={field} node={node} pluginId={meta?.plugin_id} onChange={onChange} />)}
  </div>;
}

function NodeField({ field, node, pluginId, onChange }: { field: AutomationFieldDto; node: AutomationGraphNodeDto; pluginId?: string; onChange: (node: AutomationGraphNodeDto) => void }) {
  const id = useId();
  const raw = node.config[field.id];
  const value = String(raw ?? "");
  const label = field.label || field.id;
  const set = (next: unknown) => onChange({ ...node, config: { ...node.config, [field.id]: next } });
  const [models, setModels] = useState<Array<{ id: string; name?: string }>>([]);
  const provider = field.provider || (pluginId === "google" ? "gemini" : pluginId) || "";
  useEffect(() => {
    if (field.type !== "model" || !provider) return;
    let cancelled = false;
    void getApi()?.get_models(provider)?.then((rows) => { if (!cancelled && Array.isArray(rows)) setModels(rows); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [field.type, provider]);

  let input;
  if (field.type === "project") input = <ProjectField id={id} label={label} value={value} onChange={set} />;
  else if (field.type === "ducky") input = <AgentField id={id} label={label} value={String(raw ?? node.config.profile_id ?? "")} onChange={set} />;
  else if (["boolean", "bool", "checkbox"].includes(field.type || "")) input = <ChoiceDropdown id={id} aria-label={label} value={value} options={[{ value: "", label: "Default" }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]} onChange={(next) => set(next === "" ? undefined : next === "true")} size="compact" />;
  else if (["select", "model", "multiselect"].includes(field.type || "")) {
    const choices = field.type === "model" ? models.map((model) => ({ value: model.id, label: model.name || model.id })) : (field.options || []).map((option) => ({ value: option.id, label: option.label || option.id }));
    if (field.type === "multiselect") {
      const values = Array.isArray(raw) ? raw.map(String) : [];
      for (const saved of values) if (!choices.some((choice) => choice.value === saved)) choices.push({ value: saved, label: saved });
      input = <ChoiceDropdown id={id} aria-label={label} mode="checkbox" values={values} options={choices} onChange={set} searchable size="compact" />;
    }
    else {
      const options = [{ value: "", label: "Default" }, ...choices];
      if (value && !options.some((option) => option.value === value)) options.push({ value, label: value });
      input = <ChoiceDropdown id={id} aria-label={label} value={value} options={options} onChange={set} searchable={options.length > 8} size="compact" />;
    }
  } else if (field.type === "textarea") input = <textarea id={id} aria-label={label} rows={3} value={value} onChange={(event) => set(event.target.value)} />;
  else input = <input id={id} aria-label={label} type={field.type === "number" ? "number" : "text"} value={value} onChange={(event) => set(field.type === "number" && event.target.value !== "" ? Number(event.target.value) : event.target.value)} />;
  return <div className="aw-field"><label className="aw-field-label" htmlFor={id}>{label}</label>{input}</div>;
}
