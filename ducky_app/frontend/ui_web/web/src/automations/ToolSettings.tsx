import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ChoiceDropdown, type ChoiceOption } from "../components/ChoiceDropdown";
import { getApi } from "../hooks/usePanelApi";
import type { AutomationGraphNodeDto, McpToolDto, McpToolParameterDto } from "../types/panel";

function readArguments(node: AutomationGraphNodeDto): { values: Record<string, unknown>; valid: boolean; text: string } {
  const raw = node.config.arguments;
  const text = raw !== undefined ? JSON.stringify(raw, null, 2) : String(node.config.arguments_json || "");
  try {
    const parsed = raw !== undefined ? raw : text.trim() ? JSON.parse(text) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return { values: {}, valid: false, text };
    return { values: parsed, valid: true, text };
  } catch { return { values: {}, valid: false, text }; }
}

export function ToolSettings({ node, onChange }: { node: AutomationGraphNodeDto; onChange: (node: AutomationGraphNodeDto) => void }) {
  const [tools, setTools] = useState<McpToolDto[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const request = useRef(0);
  const refresh = useCallback(async () => {
    const revision = ++request.current;
    try {
      const catalog = await getApi()?.get_mcp_tools_catalog?.();
      if (revision !== request.current) return;
      if (!Array.isArray(catalog?.tools)) throw new Error("Tools unavailable");
      setTools(catalog.tools);
      setStatus("ready");
    } catch { if (revision === request.current) setStatus("error"); }
  }, []);
  useEffect(() => { void refresh(); return () => { request.current++; }; }, [refresh]);

  const name = String(node.config.name || "");
  const tool = tools.find((item) => item.name === name);
  const args = readArguments(node);
  const parameters = tool?.parameters || [];
  const simple = parameters.filter((parameter) => ["string", "number", "integer", "boolean"].includes(parameter.type));
  const options: ChoiceOption[] = tools.map((item) => ({ value: item.name, label: item.name, hint: item.description, group: item.category_label || "Tools" }));
  if (name && !tool) options.unshift({ value: name, label: name, hint: "Saved tool — not in the current catalog" });
  const setArgument = (parameter: string, value: unknown) => {
    const next = { ...args.values };
    if (value === undefined) delete next[parameter];
    else next[parameter] = value;
    const config: Record<string, unknown> = { ...node.config, arguments: next };
    delete config.arguments_json;
    onChange({ ...node, config });
  };
  const showAdvanced = parameters.length > 0 || Object.keys(args.values).length > 0 || !args.valid || (!!name && !tool);

  return <>
    <div className="aw-field">
      <span className="aw-field-label">Tool</span>
      <ChoiceDropdown aria-label="Tool" value={name} options={options} onChange={(next) => onChange({ ...node, config: { ...node.config, name: next } })} placeholder="Choose a tool…" searchable searchPlaceholder="Search tools" showSelectedHint={false} onOpen={() => void refresh()} size="compact" minWidth={300} emptyLabel={status === "loading" ? "Loading tools…" : "No tools available"} footer={status === "error" ? "Could not load tools — reopen to retry" : undefined} />
    </div>
    {args.valid && simple.map((parameter) => <ToolArgument key={parameter.name} parameter={parameter} value={args.values[parameter.name]} onChange={(value) => setArgument(parameter.name, value)} />)}
    {tool && !parameters.length && !showAdvanced ? <p className="aw-field-hint">This tool needs no inputs.</p> : null}
    {showAdvanced ? <details className="aw-advanced" open={!args.valid || undefined}>
      <summary>Advanced inputs</summary>
      <label className="aw-field">
        <span className="aw-field-label">Arguments JSON</span>
        <textarea aria-label="Arguments JSON" className="aw-json-input" rows={4} value={args.text} placeholder="{}" spellCheck={false} onChange={(event) => {
          const config: Record<string, unknown> = { ...node.config, arguments_json: event.target.value };
          delete config.arguments;
          onChange({ ...node, config });
        }} />
      </label>
      {!args.valid ? <p className="aw-field-error" role="status">Enter a JSON object to use the input fields above.</p> : null}
    </details> : null}
  </>;
}

function ToolArgument({ parameter, value, onChange }: { parameter: McpToolParameterDto; value: unknown; onChange: (value: unknown) => void }) {
  const id = useId();
  const label = parameter.name.replace(/_/g, " ");
  const scalar = value === undefined || value === null || ["string", "number", "boolean"].includes(typeof value);
  const numeric = parameter.type === "number" || parameter.type === "integer";
  if (!scalar || (value != null && ((numeric && typeof value !== "number") || (parameter.type === "boolean" && typeof value !== "boolean")))) return null; // Keep structured/template values intact in Advanced inputs.
  const defaultLabel = parameter.default === undefined || parameter.default === null ? "Use default" : `Default: ${String(parameter.default)}`;
  return <div className="aw-field">
    <label className="aw-field-label" htmlFor={id}>{label}{parameter.required ? <span className="aw-required" title="Required"> *</span> : null}</label>
    {parameter.type === "boolean" ? <ChoiceDropdown id={id} aria-label={label} value={value == null ? "" : String(value)} options={[{ value: "", label: defaultLabel }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]} onChange={(next) => onChange(next === "" ? undefined : next === "true")} size="compact" />
      : <input id={id} aria-label={label} type={numeric ? "number" : "text"} step={parameter.type === "integer" ? 1 : "any"} value={value == null ? "" : String(value)} placeholder={parameter.default == null ? "" : String(parameter.default)} onChange={(event) => { const next = event.target.value; onChange(next === "" ? undefined : numeric ? Number(next) : next); }} />}
    {parameter.description ? <small className="aw-field-hint">{parameter.description}</small> : null}
  </div>;
}
