import { useRef, useState, useSyncExternalStore } from "react";
import { DropdownPanel } from "./DropdownPanel";
import { EditorTabGlyph } from "./EditorTabs";
import { Icons } from "../icons/Icons";
import type { EditorTab } from "../types/panel";

/* Phones: the editor's tab row is a dropdown in the header instead (more room for the
   page). The header owns the spot; the focused editor group portals its tabs into it. */
let slot: HTMLElement | null = null;
const listeners = new Set<() => void>();

export function setHeaderTabsSlot(el: HTMLElement | null) {
  if (slot === el) return;
  slot = el;
  listeners.forEach((listener) => listener());
}

export function useHeaderTabsSlot() {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    () => slot,
    () => null,
  );
}

export function MobileTabSwitcher({ tabs, activeTabId, onActivate, onClose }: {
  tabs: EditorTab[];
  activeTabId: string | null;
  onActivate: (tabId: string) => void;
  onClose: (tabId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const active = tabs.find((tab) => tab.id === activeTabId) || tabs[0];
  if (!active) return null;
  return (
    <div className="mobile-tabs no-drag">
      <button ref={anchorRef} type="button" className="no-drag mobile-tabs-trigger" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Tabs: ${active.name}${tabs.length > 1 ? ` (${tabs.length} open)` : ""}`} title="Open tabs" onClick={() => setOpen((on) => !on)}>
        <span className="editor-tab-icon" aria-hidden="true"><EditorTabGlyph tab={active} /></span>
        <span className="mobile-tabs-name">{active.name}</span>
        <span className="mobile-tabs-caret" aria-hidden="true"><Icons.ChevronDown /></span>
      </button>
      <DropdownPanel anchorRef={anchorRef} open={open} onClose={() => setOpen(false)} placement="bottom" minWidth={240} width={300}>
        <div className="mobile-tabs-menu" role="menu" aria-label="Open tabs">
          {tabs.map((tab) => (
            <div key={tab.id} className={`mobile-tabs-row${tab.id === active.id ? " is-active" : ""}`}>
              <button type="button" role="menuitem" className="mobile-tabs-pick" aria-current={tab.id === active.id ? "true" : undefined}
                onClick={() => { onActivate(tab.id); setOpen(false); }}>
                <span className="editor-tab-icon" aria-hidden="true"><EditorTabGlyph tab={tab} /></span>
                <span className="mobile-tabs-name">{tab.name}</span>
              </button>
              <button type="button" className="icon-btn mobile-tabs-close" aria-label={`Close ${tab.name}`} title="Close"
                onClick={() => { onClose(tab.id); if (tabs.length <= 1) setOpen(false); }}>
                <Icons.Close />
              </button>
            </div>
          ))}
        </div>
      </DropdownPanel>
    </div>
  );
}
