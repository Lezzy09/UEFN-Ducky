import { useEffect, useRef } from "react";

import { ChatRefIcon } from "./ChatRefChip";
import type { ChatRef } from "./chatReferences";
import type { SlashCommand } from "./slashCommands";

interface SlashCommandMenuProps {
  commands: SlashCommand[];
  refs?: ChatRef[];
  activeIndex: number;
  onHover: (index: number) => void;
  onSelect: (command: SlashCommand) => void;
  onSelectRef?: (ref: ChatRef) => void;
}

/** Command palette above the composer. `/` commands stay first; references follow. */
export function SlashCommandMenu({
  commands,
  refs = [],
  activeIndex,
  onHover,
  onSelect,
  onSelectRef,
}: SlashCommandMenuProps) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-picker-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (commands.length === 0 && refs.length === 0) return null;

  const groups: { group: string; rows: { ref: ChatRef; index: number }[] }[] = [];
  refs.forEach((ref, i) => {
    const index = commands.length + i;
    const found = groups.find((group) => group.group === ref.group);
    if (found) found.rows.push({ ref, index });
    else groups.push({ group: ref.group, rows: [{ ref, index }] });
  });

  return (
    <div className="slash-command-menu no-drag">
      <div className="slash-command-menu-header">
        {commands.length ? "Commands" : refs[0]?.trigger === "@" ? "Mentions" : refs[0]?.trigger === "~" ? "Search" : "References"}
      </div>
      <div ref={listRef} className="slash-command-menu-list">
        {commands.map((cmd, i) => (
          <button
            key={cmd.name}
            type="button"
            data-picker-index={i}
            className={`slash-command-option${i === activeIndex ? " is-active" : ""}`}
            onMouseMove={() => onHover(i)}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onSelect(cmd)}
          >
            <span className="slash-command-option-name">
              /{cmd.name}
              {cmd.args ? <span className="slash-command-option-args"> {cmd.args}</span> : null}
            </span>
            <span className="slash-command-option-desc">{cmd.description}</span>
          </button>
        ))}
        {groups.map((group) => (
          <div key={group.group}>
            <div className="slash-command-menu-header">{group.group}</div>
            {group.rows.map(({ ref, index }) => (
              <button
                key={`${ref.trigger}:${ref.id}`}
                type="button"
                data-picker-index={index}
                className={`slash-command-option${index === activeIndex ? " is-active" : ""}`}
                onMouseMove={() => onHover(index)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onSelectRef?.(ref)}
              >
                <span className="slash-command-option-icon">
                  <ChatRefIcon href={ref.href} duckyStyle={ref.duckyStyle} iconUrl={ref.iconUrl} />
                </span>
                <span className="slash-command-option-name">{ref.label}</span>
                <span className="slash-command-option-desc">{ref.description || ref.group}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="slash-command-menu-footer">
        <kbd>↑</kbd>
        <kbd>↓</kbd>
        <span>navigate</span>
        <kbd>Tab</kbd>
        <span>complete</span>
        <kbd>Esc</kbd>
        <span>dismiss</span>
      </div>
    </div>
  );
}
