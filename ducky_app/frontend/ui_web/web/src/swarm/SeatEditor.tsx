import { useEffect, useState, useSyncExternalStore } from "react";
import {
  type CatalogModelRow,
  getCachedModels,
  loadModelsCatalog,
  subscribeModelsCatalog,
} from "../hooks/modelsCatalogCache";
import { type LaneOverlap, overlapNotes } from "./lanes";

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
  perms?: Permissions;
}

/** Up-front grants, so a run never stops mid-way for a confirmation (L1's trust_drafts). */
export const PERMISSIONS = [
  { key: "commit", label: "Commit" },
  { key: "may_release", label: "May release/publish" },
  { key: "allow_terminal", label: "Allow terminal" },
  { key: "trust_drafts", label: "Trust plugin drafts" },
] as const;
export type Permission = (typeof PERMISSIONS)[number]["key"];
export type Permissions = Partial<Record<Permission, boolean>>;

/** Switches for a seat (`target={seat: name}`) or a team (`target={group: name}`). */
export function PermissionSwitches(props: {
  target: SwarmEdit;
  perms?: Permissions;
  onEdit: (edit: SwarmEdit) => void;
}) {
  return (
    <div className="swarm-perms">
      {PERMISSIONS.map(({ key, label }) => (
        <label key={key}>
          <input
            type="checkbox"
            aria-label={label}
            checked={!!props.perms?.[key]}
            onChange={(e) => props.onEdit({ ...props.target, [key]: e.target.checked })}
          />
          {label}
        </label>
      ))}
    </div>
  );
}

const STEP_DRAG = "application/x-swarm-step";

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
  /** laneOverlaps() over every seat in the card. */
  overlaps?: LaneOverlap[];
}) {
  const { seat, onEdit } = props;
  const models = useCatalog(props.models);
  const options = models.map(qualifiedModel);
  if (seat.model && !options.includes(seat.model)) options.unshift(seat.model);
  const steps = seat.sub_plan.steps;
  const [newStep, setNewStep] = useState("");
  const lane = seat.paths.join(", ");
  const notes = overlapNotes(seat.name, props.overlaps ?? []);

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
      {notes.map((n) => (
        <div key={n} className="swarm-lane-overlap" role="alert">
          {n}
        </div>
      ))}
      <PermissionSwitches target={{ seat: seat.name }} perms={seat.perms} onEdit={onEdit} />
      <ol
        className="swarm-seat-steps"
        aria-label={`${seat.name} steps`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          try {
            const { seat: from, step } = JSON.parse(e.dataTransfer.getData(STEP_DRAG));
            if (from && step && from !== seat.name) onEdit({ seat: from, move_step: step, to_seat: seat.name });
          } catch {
            // not a step drag
          }
        }}
      >
        {steps.map((step) => (
          <li
            key={step.content}
            draggable
            onDragStart={(e) =>
              e.dataTransfer.setData(STEP_DRAG, JSON.stringify({ seat: seat.name, step: step.content }))
            }
          >
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
