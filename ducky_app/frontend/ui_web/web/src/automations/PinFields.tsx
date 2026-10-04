import { useEffect, useId, useRef, useState } from "react";
import { ChoiceDropdown } from "../components/ChoiceDropdown";
import { getApi } from "../hooks/usePanelApi";
import { Icons } from "../icons/Icons";
import type { AutomationGraphDto, AutomationGraphNodeDto, FileRefDto, PinDto, PinType } from "../types/panel";
import { cleanType, PIN_TYPE_LABELS, shortValue, type NodePins } from "./pins";

const FILE_ACCEPT: Partial<Record<PinType, string>> = { image: "image", images: "image", audio: "audio", video: "video", mesh: "mesh", pdf: "pdf", svg: "svg", file: "any" };

function asRefs(value: unknown): FileRefDto[] {
  const list = Array.isArray(value) ? value : value ? [value] : [];
  return list.flatMap((item) => item && typeof item === "object" && "path" in (item as object) ? [item as FileRefDto]
    : typeof item === "string" && item ? [{ kind: "file", path: item, name: item.replace(/\\/g, "/").split("/").pop() || item }] : []);
}

/** Pick files on this PC for an Input node or an unwired file pin. */
export function FilePicker({ id, label, value, accept, multiple, disabled, onChange }: {
  id?: string; label: string; value: unknown; accept: string; multiple?: boolean; disabled?: boolean; onChange: (value: FileRefDto | FileRefDto[] | undefined) => void;
}) {
  const refs = asRefs(value);
  const [error, setError] = useState("");
  const pick = async () => {
    setError("");
    const res = await getApi()?.pick_workflow_files?.(accept, !!multiple);
    if (!res) { setError("The file picker isn't available here."); return; }
    if (res.ok === false) { setError(res.error || "Could not open the file picker."); return; }
    const files = res.files || [];
    if (!files.length) return;
    onChange(multiple ? [...refs, ...files] : files[0]);
  };
  return <div className="aw-file-picker">
    {refs.length ? <ul className="aw-file-list">
      {refs.map((ref, index) => <li key={`${ref.path}-${index}`} title={ref.path}>
        <Icons.File /><span>{ref.name}</span>
        {disabled ? null : <button type="button" className="aw-icon-button" aria-label={`Remove ${ref.name}`} onClick={() => onChange(multiple ? refs.filter((_, at) => at !== index) : undefined)}><Icons.Close /></button>}
      </li>)}
    </ul> : null}
    <button type="button" id={id} className="aw-file-pick" aria-label={label} disabled={disabled} onClick={() => void pick()}>
      <Icons.Plus /> {refs.length && !multiple ? "Pick another file" : multiple ? "Add files" : "Pick a file"}
    </button>
    {error ? <small className="aw-field-error" role="status">{error}</small> : null}
  </div>;
}

/** The editor for an unwired input pin: text, number, yes/no, data or a file picker. */
export function PinValueEditor({ pin, value, disabled, onChange }: { pin: PinDto; value: unknown; disabled?: boolean; onChange: (value: unknown) => void }) {
  const id = useId();
  const type = cleanType(pin.type);
  const label = pin.label;
  const fallback = pin.default == null || pin.default === "" ? "" : `Default: ${typeof pin.default === "string" ? pin.default : JSON.stringify(pin.default)}`;
  if (FILE_ACCEPT[type]) return <FilePicker id={id} label={label} value={value} accept={FILE_ACCEPT[type]!} multiple={type === "images"} disabled={disabled} onChange={onChange} />;
  if (type === "boolean") {
    return <ChoiceDropdown id={id} aria-label={label} value={value === true ? "true" : value === false ? "false" : ""} size="compact" disabled={disabled}
      options={[{ value: "", label: "Not set" }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]}
      onChange={(next) => onChange(next === "" ? undefined : next === "true")} />;
  }
  if (type === "number") {
    return <input id={id} aria-label={label} type="text" inputMode="decimal" disabled={disabled} value={value == null ? "" : String(value)} placeholder={pin.default == null ? "" : String(pin.default)}
      onChange={(event) => { const text = event.target.value; const number = Number(text); onChange(text.trim() === "" ? undefined : Number.isFinite(number) ? number : text); }} />;
  }
  if (type === "text") {
    return <textarea id={id} aria-label={label} rows={2} disabled={disabled} value={value == null ? "" : String(value)} placeholder={fallback || "Type it here, or wire text in"} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)} />;
  }
  return <input id={id} aria-label={label} type="text" disabled={disabled} value={value == null ? "" : typeof value === "string" ? value : JSON.stringify(value)} placeholder={fallback || "A value, or {{field}} from an earlier step"}
    onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)} />;
}

/** Details panel: the inputs you can type (a wired one shows on the canvas, and its wire
 *  can be clicked to disconnect it), and what came out last run, folded. */
export function PinsSection({ node, pins, graph, outputs, frozen, onNodeChange }: {
  node: AutomationGraphNodeDto;
  pins: NodePins;
  graph: AutomationGraphDto;
  outputs?: Record<string, unknown>;
  frozen: boolean;
  onNodeChange: (node: AutomationGraphNodeDto) => void;
}) {
  const setHere = (node.config.inputs && typeof node.config.inputs === "object" ? node.config.inputs : {}) as Record<string, unknown>;
  // Run workflow nodes saved before pins kept their values in config.args.
  const legacy = (node.type === "workflow.call" && node.config.args && typeof node.config.args === "object" ? node.config.args : {}) as Record<string, unknown>;
  const setValue = (pin: string, value: unknown) => {
    const inputs = { ...setHere };
    if (value === undefined) delete inputs[pin]; else inputs[pin] = value;
    const config: Record<string, unknown> = { ...node.config, inputs };
    if (pin in legacy) { const args = { ...legacy }; delete args[pin]; config.args = args; }
    onNodeChange({ ...node, config });
  };
  const isWired = (pin: string) => graph.edges.some((edge) => edge.kind === "data" && edge.target === node.id && edge.target_pin === pin);
  const typed = pins.inputs.filter((pin) => !isWired(pin.id));
  if (!typed.length && !(pins.outputs.length && outputs)) return null;
  return <>
    {typed.length ? <fieldset className="aw-insp-section aw-pins-section" disabled={frozen}>
      <legend>Inputs</legend>
      {typed.map((pin) => <div key={pin.id} className="aw-field aw-pin-field">
        <span className="aw-pin-field-head"><span className={`aw-pin-dot aw-pin-type--${cleanType(pin.type)}`} aria-hidden="true" />{pin.label}{pin.required ? <span className="aw-required" title="Needed"> *</span> : null}<small>{PIN_TYPE_LABELS[cleanType(pin.type)]}</small></span>
        <PinValueEditor pin={pin} value={setHere[pin.id] ?? legacy[pin.id]} disabled={frozen} onChange={(value) => setValue(pin.id, value)} />
        {pin.description ? <small className="aw-field-hint">{pin.description}</small> : null}
      </div>)}
    </fieldset> : null}
    {pins.outputs.length && outputs ? <details className="aw-insp-section aw-pins-section aw-last-run">
      <summary className="aw-pins-title">Last run</summary>
      {pins.outputs.map((pin) => <div key={pin.id} className="aw-pin-out">
        <span className="aw-pin-field-head"><span className={`aw-pin-dot aw-pin-type--${cleanType(pin.type)}`} aria-hidden="true" />{pin.label}</span>
        <OutputValue value={outputs[pin.id]} />
      </div>)}
    </details> : null}
  </>;
}

const PICTURE = /\.(png|jpe?g|webp|gif|bmp|svg)$/i;

function OutputValue({ value }: { value: unknown }) {
  if (value === undefined) return <small className="aw-field-hint">Nothing came out.</small>;
  const refs = (Array.isArray(value) ? value : [value]).filter((item): item is FileRefDto => !!item && typeof item === "object" && "path" in (item as object));
  if (refs.length) {
    return <div className="aw-pin-out-files">
      {refs.slice(0, 12).map((ref, index) => <span key={`${ref.path}-${index}`} className="aw-pin-out-file" title={ref.path}>
        {ref.url && (ref.kind === "image" || PICTURE.test(ref.path)) ? <img src={ref.url} alt="" draggable={false} loading="lazy" /> : <Icons.File />}
        <span>{ref.name}</span>
      </span>)}
      {refs.length > 12 ? <small className="aw-field-hint">and {refs.length - 12} more</small> : null}
    </div>;
  }
  if (typeof value === "string" && value.length > 40) return <pre className="aw-pin-out-text">{value}</pre>;
  if (value && typeof value === "object" && !Array.isArray(value) && !("path" in (value as object))) return <pre className="aw-pin-out-text">{JSON.stringify(value, null, 2)}</pre>;
  return <span className="aw-pin-out-value">{shortValue(value) || "(empty)"}</span>;
}

/** Names of the inputs an If / Expression / Text template takes (its input pins). */
export function NamesField({ id, label, value, fallback, disabled, onChange }: { id: string; label: string; value: unknown; fallback: string[]; disabled?: boolean; onChange: (names: string[]) => void }) {
  const names = Array.isArray(value) && value.length ? value.map(String) : fallback;
  const [draft, setDraft] = useState("");
  const add = () => {
    const name = draft.trim().replace(/[^\w$]/g, "_");
    if (!name || names.includes(name)) return;
    onChange([...names, name]);
    setDraft("");
  };
  return <div className="aw-names" id={id} aria-label={label} role="group">
    {names.map((name) => <span key={name} className="aw-name-chip">{name}
      {disabled || names.length === 1 ? null : <button type="button" aria-label={`Remove input ${name}`} onClick={() => onChange(names.filter((item) => item !== name))}><Icons.Close /></button>}
    </span>)}
    {disabled ? null : <input aria-label="New input name" placeholder="Add an input" value={draft} onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} onBlur={add} />}
  </div>;
}

/** An If / Expression condition with a live check of what is wrong. */
export function ExpressionField({ id, label, value, names, disabled, onChange }: { id: string; label: string; value: string; names: string[]; disabled?: boolean; onChange: (value: string) => void }) {
  const [error, setError] = useState("");
  const timer = useRef(0);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!value.trim()) { setError(""); return; }
    timer.current = window.setTimeout(() => {
      void getApi()?.check_workflow_expression?.(value).then((res) => setError(res?.error || "")).catch(() => setError(""));
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [value]);
  return <>
    <textarea id={id} aria-label={label} className="aw-json-input aw-expression" rows={2} spellCheck={false} disabled={disabled} value={value}
      placeholder={names.length ? `${names[0]} > 10` : "score > 10"} onChange={(event) => onChange(event.target.value)} />
    {error ? <small className="aw-field-error" role="status">{error}</small>
      : <small className="aw-field-hint">Use {names.map((name) => <code key={name}>{name}</code>).reduce<React.ReactNode[]>((all, item, index) => index ? [...all, ", ", item] : [item], [])}, run fields like <code>score</code>, && || !, ? :, .length, .includes(), round(), max()…</small>}
  </>;
}
