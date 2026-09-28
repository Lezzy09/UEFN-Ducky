import { useEffect, useRef, useState } from "react";

/** Edits the text in its place on the card. Enter/blur commits; Escape cancels. */
export function InlineNodeText({ value, label, placeholder, multiline = false, onCommit }: {
  value: string;
  label: string;
  placeholder?: string;
  multiline?: boolean;
  onCommit: (value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const finished = useRef(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (!editing) {
      if (restoreFocus.current) { restoreFocus.current = false; buttonRef.current?.focus({ preventScroll: true }); }
      return;
    }
    inputRef.current?.focus({ preventScroll: true });
    inputRef.current?.select();
  }, [editing]);

  const finish = (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    setEditing(false);
    const next = text.trim();
    if (save && next !== value && (multiline || next)) onCommit(next);
  };
  const className = `aw-inline-text${multiline ? " aw-inline-text--description" : " aw-inline-text--name"}`;
  const inputProps = {
    className: `${className} aw-inline-input`,
    value: text,
    "aria-label": label,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setText(event.target.value),
    onBlur: () => finish(true),
    onKeyDown: (event: React.KeyboardEvent) => {
      event.stopPropagation();
      if (event.nativeEvent.isComposing) return;
      if (event.key === "Escape" || (event.key === "Enter" && !event.shiftKey)) {
        event.preventDefault();
        restoreFocus.current = true;
        finish(event.key === "Enter");
      }
    },
  };
  return <div className="aw-inline-edit" onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
    {editing ? (multiline
      ? <textarea {...inputProps} rows={2} ref={(element) => { inputRef.current = element; }} />
      : <input {...inputProps} ref={(element) => { inputRef.current = element; }} />)
      : <button ref={buttonRef} type="button" className={`${className}${!value ? " is-empty" : ""}`} aria-label={`Edit ${label.toLowerCase()}`} title={value ? `${value} — Click to edit` : `Click to edit ${label.toLowerCase()}`} onClick={() => { finished.current = false; setText(value); setEditing(true); }}>
        {value || placeholder}
      </button>}
  </div>;
}
