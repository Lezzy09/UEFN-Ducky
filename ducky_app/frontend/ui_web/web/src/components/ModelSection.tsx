/**
 * One collapsible section of the model picker: "API", "Codex", "Claude Code", … inside a
 * gateway. Every section is an accordion the person can fold (an API list can hold dozens
 * of models), and the fold is remembered per gateway and section. A section with the
 * picked model, or with a search hit, opens itself so the pick is never hidden.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Icons } from "../icons/Icons";

const STORAGE_KEY = "ducky.modelPicker.sections";

type Folds = Record<string, boolean>;

function readFolds(): Folds {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return parsed && typeof parsed === "object" ? (parsed as Folds) : {};
  } catch {
    return {};
  }
}

function writeFold(key: string, collapsed: boolean): void {
  try {
    const folds = readFolds();
    if (collapsed) folds[key] = true;
    else delete folds[key];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(folds));
  } catch {
    // Storage is a per-viewer convenience; the picker works without it.
  }
}

export function isSectionCollapsed(key: string): boolean {
  return readFolds()[key] === true;
}

export interface ModelSectionProps {
  /** Storage key: "<gateway>:<section>" so folds are remembered per gateway. */
  storageKey: string;
  label: string;
  /** Shown after the label: a count, "Unavailable", "Checking…". */
  meta?: ReactNode;
  /** A search is on, or the picked model sits in here: the section stays open. */
  forceOpen?: boolean;
  disabled?: boolean;
  children: ReactNode;
}

export function ModelSection({ storageKey, label, meta, forceOpen, disabled, children }: ModelSectionProps) {
  const [collapsed, setCollapsed] = useState(() => isSectionCollapsed(storageKey));
  useEffect(() => {
    setCollapsed(isSectionCollapsed(storageKey));
  }, [storageKey]);
  const open = !!forceOpen || !collapsed;
  return (
    <div className={`model-selector-provider-group model-selector-section${open ? "" : " is-collapsed"}`}>
      <button
        type="button"
        className={`model-selector-provider-label${open ? "" : " is-collapsed"}${disabled ? " is-disabled" : ""}`}
        aria-expanded={open}
        onClick={() => {
          const next = open; // open → fold, folded → open
          setCollapsed(next);
          writeFold(storageKey, next);
        }}
      >
        <span className="model-selector-provider-caret">
          <Icons.ChevronDown />
        </span>
        <span className="model-selector-provider-name">{label}</span>
        {meta}
      </button>
      {open && children}
    </div>
  );
}
