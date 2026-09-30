import { useId } from "react";
import { ChoiceDropdown, type ChoiceOption } from "../components/ChoiceDropdown";
import { Icons } from "../icons/Icons";
import type { AutomationGraphNodeDto, AutomationSummaryDto } from "../types/panel";

type Row = { name: string; [key: string]: unknown };

function rowsOf(raw: unknown): Row[] {
  return Array.isArray(raw) ? raw.filter((row): row is Row => !!row && typeof row === "object").map((row) => ({ ...row, name: String(row.name ?? "") })) : [];
}

/** Inputs (name + default) and Return (name + value) lists. */
export function NamedValueList({ node, field, valueKey, valueLabel, valuePlaceholder, addLabel, onChange }: {
  node: AutomationGraphNodeDto;
  field: string;
  valueKey: "default" | "value";
  valueLabel: string;
  valuePlaceholder: string;
  addLabel: string;
  onChange: (node: AutomationGraphNodeDto) => void;
}) {
  const id = useId();
  const rows = rowsOf(node.config[field]);
  const set = (next: Row[]) => onChange({ ...node, config: { ...node.config, [field]: next } });
  const patch = (index: number, change: Partial<Row>) => set(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));
  return <div className="aw-field aw-named-values">
    {rows.length ? <div className="aw-named-head" aria-hidden="true"><span>Name</span><span>{valueLabel}</span></div> : null}
    {rows.map((row, index) => <div className="aw-named-row" key={index}>
      <input id={`${id}-${index}`} aria-label={`Name ${index + 1}`} value={row.name} placeholder="name" spellCheck={false}
        onChange={(event) => patch(index, { name: event.target.value.replace(/[^\w.-]/g, "_") })} />
      <input aria-label={`${valueLabel} ${index + 1}`} value={String(row[valueKey] ?? "")} placeholder={valuePlaceholder} spellCheck={false}
        onChange={(event) => patch(index, { [valueKey]: event.target.value })} />
      <button type="button" className="aw-icon-button" aria-label={`Remove ${row.name || `row ${index + 1}`}`} title="Remove" onClick={() => set(rows.filter((_, i) => i !== index))}><Icons.Close /></button>
    </div>)}
    <button type="button" className="aw-named-add" onClick={() => set([...rows, { name: "", [valueKey]: "" }])}><Icons.Plus /> {addLabel}</button>
  </div>;
}

/** Run workflow: pick the workflow, fill its inputs, see what it returns. */
export function CallSettings({ node, workflows, currentId, onChange, onOpen }: {
  node: AutomationGraphNodeDto;
  workflows: AutomationSummaryDto[];
  currentId?: string;
  onChange: (node: AutomationGraphNodeDto) => void;
  onOpen?: (id: string) => void;
}) {
  const id = useId();
  const target = String(node.config.workflow_id || "");
  const picked = workflows.find((row) => row.id === target);
  const args = (node.config.args && typeof node.config.args === "object" && !Array.isArray(node.config.args) ? node.config.args : {}) as Record<string, unknown>;
  const options: ChoiceOption[] = workflows.filter((row) => row.id !== currentId).map((row) => ({
    value: row.id,
    label: row.name || "Untitled",
    hint: row.signature ? describeSignature(row.signature) : "No Inputs node yet",
    group: row.trigger?.kind === "function" ? "Reusable workflows" : "Other workflows",
  })).sort((a, b) => (a.group === b.group ? 0 : a.group === "Reusable workflows" ? -1 : 1));
  if (target && !picked) options.unshift({ value: target, label: "Missing workflow", hint: "Deleted, or not shared with you" });
  const choose = (next: string) => {
    const row = workflows.find((item) => item.id === next);
    const previous = picked?.name || "";
    const label = !node.label || node.label === "Run workflow" || node.label === previous ? row?.name || node.label : node.label;
    onChange({ ...node, label, config: { ...node.config, workflow_id: next } });
  };
  const setArg = (name: string, value: string) => {
    const next = { ...args, [name]: value };
    if (value === "") delete next[name];
    onChange({ ...node, config: { ...node.config, args: next } });
  };
  const share = node.config.share === true;
  const inputs = picked?.signature?.inputs || [];
  const extra = Object.keys(args).filter((name) => !inputs.some((input) => input.name === name));
  return <>
    <div className="aw-field">
      <label className="aw-field-label" htmlFor={id}>Workflow</label>
      <div className="aw-call-pick">
        <ChoiceDropdown id={id} aria-label="Workflow" value={target} options={options} onChange={choose} placeholder="Choose a workflow…" searchable={options.length > 6} searchPlaceholder="Search workflows" showSelectedHint={false} size="compact" minWidth={260} emptyLabel="No other workflows yet" />
        {picked && onOpen ? <button type="button" className="aw-icon-button" title={`Open ${picked.name}`} aria-label={`Open ${picked.name}`} onClick={() => onOpen(picked.id)}><Icons.Workflow /></button> : null}
      </div>
    </div>
    {picked && !picked.signature?.inputs.length && !extra.length ? <p className="aw-field-hint">It takes no inputs. Add an Inputs node to it to pass values in.</p> : null}
    {[...inputs.map((input) => ({ name: input.name, placeholder: input.default ? `Default: ${input.default}` : "Value or {{field}}" })), ...extra.map((name) => ({ name, placeholder: "Not an input anymore" }))].map((input) => (
      <ArgField key={input.name} name={input.name} placeholder={input.placeholder} value={String(args[input.name] ?? "")} onChange={(value) => setArg(input.name, value)} />
    ))}
    <label className="aw-check">
      <input type="checkbox" checked={share} onChange={(event) => onChange({ ...node, config: { ...node.config, share: event.target.checked || undefined } })} />
      <span>Share this run's data <small className="aw-field-hint">It sees every field from earlier steps, and every field it sets comes back.</small></span>
    </label>
    {picked ? <p className="aw-field-hint">
      {picked.signature?.outputs.length ? <>Next steps can use {picked.signature.outputs.map((name, i) => <span key={name}>{i ? ", " : ""}<code>{name}</code></span>)}.</> : "It returns nothing yet. Add a Return node to it to give values back."}
      {" "}Type <code>{"{{field}}"}</code> to pass a value from an earlier step. If it has Return nodes and none is reached, this path stops here.
    </p> : null}
  </>;
}

function ArgField({ name, placeholder, value, onChange }: { name: string; placeholder: string; value: string; onChange: (value: string) => void }) {
  const id = useId();
  return <div className="aw-field">
    <label className="aw-field-label" htmlFor={id}>{name}</label>
    <input id={id} aria-label={name} value={value} placeholder={placeholder} spellCheck={false} onChange={(event) => onChange(event.target.value)} />
  </div>;
}

export function describeSignature(signature: NonNullable<AutomationSummaryDto["signature"]>): string {
  const inputs = signature.inputs.map((input) => input.name).join(", ") || "nothing";
  const outputs = signature.outputs.join(", ") || "nothing";
  return `Takes ${inputs} · returns ${outputs}`;
}
