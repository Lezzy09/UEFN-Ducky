import { useId, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { getApi } from "../../hooks/usePanelApi";
import { copyText } from "../../utils/copyText";
import type { OpenFileHandler } from "../../types/richContent";
import { basename } from "../../verse-editor/utils/isVerseFile";
import { classifyRichRef } from "./classifyRichRef";

function openChip(text: string, onOpenFile?: OpenFileHandler): void {
  const ref = classifyRichRef(text);
  if (ref.open?.type === "file") {
    const path = ref.open.path;
    const name = basename(path);
    if (onOpenFile) onOpenFile(path, name);
    else void getApi()?.open_project_file(path);
    return;
  }
  if (ref.open?.type === "asset") {
    void getApi()?.open_asset_in_uefn?.(ref.open.path);
    return;
  }
  void copyText(ref.text);
}

/** Enter or Space runs an inline role="button" span the way a real button would. */
export function onActivateKey(run: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    run();
  };
}

export function RichCodeChip({ text, onOpenFile }: { text: string; onOpenFile?: OpenFileHandler }) {
  const ref = classifyRichRef(text);
  const tipId = useId();
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const show = (el: HTMLElement) => {
    const box = el.getBoundingClientRect();
    setPos({ x: box.left, y: box.bottom + 6 });
  };

  const tip = pos && typeof document !== "undefined"
    ? createPortal(
        <div
          id={tipId}
          role="tooltip"
          className="rich-ref-tip"
          ref={(node) => {
            if (!node) return;
            node.style.setProperty("left", `${pos.x}px`);
            node.style.setProperty("top", `${pos.y}px`);
          }}
        >
          <div className="rich-ref-tip-kind">{ref.label}</div>
          <div className="rich-ref-tip-name">{ref.text}</div>
          <div className="rich-ref-tip-hint">{ref.hint}</div>
        </div>,
        document.body,
      )
    : null;

  // A span, not a <button>: a button is always its own box, so a long name wrapped inside it
  // with centred lines on a phone. An inline span flows and wraps with the sentence.
  const run = () => openChip(text, onOpenFile);
  return (
    <>
      <span
        role="button"
        tabIndex={0}
        className={`rich-code rich-code--inline rich-ref rich-ref--${ref.kind} ${ref.open ? "rich-ref--open" : "rich-ref--copy"}`}
        aria-describedby={pos ? tipId : undefined}
        aria-label={`${ref.label}: ${ref.text}. ${ref.hint}`}
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => show(e.currentTarget)}
        onBlur={() => setPos(null)}
        onClick={run}
        onKeyDown={onActivateKey(run)}
      >
        {text}
      </span>
      {tip}
    </>
  );
}
