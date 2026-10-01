import { useRef, useState } from "react";
import { DropdownPanel } from "../components/DropdownPanel";

/** Quick picks for a node or group; any other emoji can be typed or pasted. */
export const ICON_CHOICES = [
  "⚡", "▶️", "💬", "⏰", "🛠️", "🔧", "⚙️", "🧩", "🔀", "🔁", "⏳", "🏁",
  "📤", "📥", "↩️", "🚀", "🎮", "🧍", "🔎", "🩺", "📂", "💾", "📦", "🗺️",
  "🏝️", "🎯", "🏆", "💰", "🛡️", "⚔️", "🔥", "❄️", "🌟", "💡", "🎨", "🎵",
  "🔔", "📣", "✉️", "🤖", "🦆", "🧠", "📊", "✅", "❌", "⚠️", "🧪", "🧱",
];

/** One emoji (or a very short symbol); "" when it isn't one. */
export function cleanIcon(value: string): string {
  const icon = value.trim();
  return icon && [...icon].length <= 8 && !/\s/.test(icon) ? icon : "";
}

/** The icon at the top right of the details. While it can be changed it is a button that
 *  opens the picker: quick picks, any emoji typed or pasted, or back to the default. */
export function IconPicker({ icon, shown, label, disabled, onChange }: {
  /** The icon picked for it ("" or undefined: the default for its kind). */
  icon?: string;
  /** What is drawn now (the picked icon or the default). */
  shown: React.ReactNode;
  label: string;
  disabled?: boolean;
  onChange: (icon: string) => void;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const pick = (value: string) => { setOpen(false); setTyped(""); if (value !== (icon || "")) onChange(value); };
  if (disabled) return <span className="aw-insp-top-icon" aria-hidden="true">{shown}</span>;
  const own = cleanIcon(typed);
  return <>
    <button ref={anchor} type="button" className="aw-insp-top-icon aw-icon-pick" aria-label={label} title="Change the icon" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      {shown}
    </button>
    <DropdownPanel anchorRef={anchor} open={open} onClose={() => setOpen(false)} width={300}>
      <div className="aw-icon-panel" role="dialog" aria-label="Pick an icon" onKeyDown={(event) => { event.stopPropagation(); if (event.key === "Escape") setOpen(false); }}>
        <div className="aw-icon-grid">
          {ICON_CHOICES.map((emoji) => <button key={emoji} type="button" aria-label={`Icon ${emoji}`} aria-pressed={icon === emoji} onClick={() => pick(emoji)}>{emoji}</button>)}
        </div>
        <form className="aw-icon-own" onSubmit={(event) => { event.preventDefault(); if (own) pick(own); }}>
          <input aria-label="Any emoji" placeholder="Type or paste any emoji" value={typed} maxLength={16} spellCheck={false} onChange={(event) => setTyped(event.target.value)} />
          <button type="submit" disabled={!own}>Use</button>
        </form>
        {icon ? <button type="button" className="aw-icon-reset" onClick={() => pick("")}>Back to the default icon</button> : null}
      </div>
    </DropdownPanel>
  </>;
}
