import { initials, personTone, presenceText, type Presence } from "./scopeBarText";

/** "iliya kovachki · Laptop · Editing Untitled island 1". */
export function presenceLabel(row: Presence, plugin?: string): string {
  return [row.me || row.self ? "You" : row.name, row.device, presenceText(row, plugin)].filter(Boolean).join(" · ");
}

/**
 * One person's round avatar: their initials on their own colour (the same on every PC), with
 * a ring while they edit. Decorative where a name sits next to it (`labelled` false); the
 * bar's strip names everyone in its button, and the drawer lists them all in words.
 */
export function PresenceAvatar({ row, plugin, labelled = true }: { row: Presence; plugin?: string; labelled?: boolean }) {
  const label = presenceLabel(row, plugin);
  return (
    <span
      className={`plugin-scope-avatar plugin-scope-avatar--${row.state} plugin-scope-avatar--tone-${personTone(row.id)}`}
      title={label}
      {...(labelled ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {initials(row.name)}
    </span>
  );
}
