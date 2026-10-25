import { useEffect, useState, useSyncExternalStore } from "react";
import {
  type CatalogModelRow,
  getCachedModels,
  loadModelsCatalog,
  subscribeModelsCatalog,
} from "../hooks/modelsCatalogCache";

/** One entry of ducky_swarm_create's `edits[]` (see swarm_preview._job_edits / _tree_edits). */
export type SwarmEdit = Record<string, unknown>;

export interface SwarmStep {
  content: string;
  body_markdown?: string;
}

/** A seat as the swarm_builder preview tree sends it. */
export interface SwarmSeat {
  name: string;
  job: string;
  model: string;
  paths: string[];
  sub_plan: { title: string; steps: SwarmStep[] };
}

export function qualifiedModel(row: CatalogModelRow): string {
  return row.providerKey ? `${row.providerKey}:${row.id}` : row.id;
}

/** Comma or newline separated lane text → clean path list. */
export function parseLane(text: string): string[] {
  return text.split(/[,\n]/).map((p) => p.trim()).filter(Boolean);
}

function useCatalog(models?: CatalogModelRow[]): CatalogModelRow[] {
  const cached = useSyncExternalStore(subscribeModelsCatalog, getCachedModels);
  useEffect(() => {
    if (!models) void loadModelsCatalog();
  }, [models]);
  return models ?? cached ?? [];
}

/** Edit text that reports once, on blur or Enter, and only when it changed. */
function CommitInput(props: { value: string; label: string; onCommit: (next: string) => void }) {
  const [text, setText] = useState(props.value);
  useEffect(() => setText(props.value), [props.value]);
  const commit = () => {
    const next = text.trim();
    if (next && next !== props.value) props.onCommit(next);
    else setText(props.value);
  };
  return (
    <input
      aria-label={props.label}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

export function SeatEditor(props: {
  seat: SwarmSeat;
  onEdit: (edit: SwarmEdit) => void;
  /** Defaults to the shared models catalog. */
  models?: CatalogModelRow[];
}) {
  const { seat, onEdit } = props;
  const models = useCatalog(props.models);
  const options = models.map(qualifiedModel);
  if (seat.model && !options.includes(seat.model)) options.unshift(seat.model);
  const steps = seat.sub_plan.steps;
  const [newStep, setNewStep] = useState("");
  const lane = seat.paths.join(", ");

  return (
    <div className="swarm-seat-editor" data-seat={seat.name}>
      <label>
        Name
        <CommitInput label="Seat name" value={seat.name} onCommit={(to) => onEdit({ rename: seat.job, to })} />
      </label>
      <label>
        Model
        <select
          aria-label="Model"
          value={seat.model}
          onChange={(e) => onEdit({ seat: seat.name, model: e.target.value })}
        >
          {options.map((m) => (
            <option key={m} value={m}>
              {models.find((r) => qualifiedModel(r) === m)?.name || m}
            </option>
          ))}
        </select>
      </label>
      <label>
        Lane
        <CommitInput
          label="Lane paths"
          value={lane}
          onCommit={(text) => onEdit({ seat: seat.name, paths: parseLane(text) })}
        />
      </label>
      <ol className="swarm-seat-steps">
        {steps.map((step) => (
          <li key={step.content}>
            <CommitInput
              label={`Step: ${step.content}`}
              value={step.content}
              onCommit={(to) => onEdit({ seat: seat.name, rename_step: step.content, to })}
            />
            <button
              type="button"
              aria-label={`Drop step ${step.content}`}
              disabled={steps.length < 2}
              title={steps.length < 2 ? "A sub plan needs one step: drop the job instead" : undefined}
              onClick={() => onEdit({ seat: seat.name, drop_step: step.content })}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const content = newStep.trim();
          if (!content) return;
          onEdit({ seat: seat.name, add_step: content });
          setNewStep("");
        }}
      >
        <input aria-label="New step" value={newStep} onChange={(e) => setNewStep(e.target.value)} />
        <button type="submit">Add step</button>
      </form>
      <button type="button" className="swarm-seat-drop" onClick={() => onEdit({ drop: seat.job })}>
        Drop job
      </button>
    </div>
  );
}
