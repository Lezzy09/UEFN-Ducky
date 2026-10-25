import type { SwarmEdit } from "./SeatEditor";

/** A group as the swarm_builder preview tree sends it. */
export interface SwarmGroup {
  group: string;
  muted?: boolean;
  /** Plan step id this group's seats wait for (S2's start-later groups). */
  start_after?: string;
}

export interface PlanStepOption {
  id: string;
  content: string;
}

export function GroupEditor(props: {
  group: SwarmGroup;
  onEdit: (edit: SwarmEdit) => void;
  /** Steps the group can start after. */
  steps?: PlanStepOption[];
}) {
  const { group, onEdit, steps = [] } = props;
  const name = group.group;
  return (
    <div className="swarm-group-editor" data-group={name}>
      <label>
        Name
        <input
          aria-label="Group name"
          defaultValue={name}
          key={name}
          onBlur={(e) => {
            const to = e.target.value.trim();
            if (to && to !== name) onEdit({ rename: name, to });
            else e.target.value = name;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
        />
      </label>
      <label>
        <input
          type="checkbox"
          aria-label="Muted"
          checked={!!group.muted}
          onChange={(e) => onEdit(e.target.checked ? { mute: name } : { unmute: name })}
        />
        Muted
      </label>
      <label>
        Start after step…
        <select
          aria-label="Start after step"
          value={group.start_after || ""}
          onChange={(e) => onEdit({ group: name, start_after: e.target.value })}
        >
          <option value="">At once</option>
          {steps.map((s) => (
            <option key={s.id} value={s.id}>
              {s.content}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
