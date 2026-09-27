import { useId, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { DuckyAvatar } from "./ducky/DuckyAvatars";
import { chatRefDisplayName, parseChatRefHref, type ChatRefKind } from "./chatReferences";
import { useChatRefFace, type ChatRefFace } from "./chatRefFaces";

function isImageIcon(value: string): boolean {
  return (
    value.startsWith("data:image/") ||
    /^https?:\/\//i.test(value) ||
    /\.(png|jpe?g|svg|webp|gif)(\?|$)/i.test(value)
  );
}

function refTip(kind: ChatRefKind | undefined): { kind: string; hint: string } {
  if (kind === "pipeline") return { kind: "Pipeline", hint: "Open this pipeline. Type your request after the reference to run it." };
  if (kind === "ducky") return { kind: "Chat", hint: "Open that chat" };
  if (kind === "profile") return { kind: "Ducky", hint: "Open this ducky" };
  if (kind === "subskill") return { kind: "Subskill", hint: "Open in Skills" };
  if (kind === "mcp") return { kind: "MCP", hint: "Open in MCPs" };
  if (kind === "plugin") return { kind: "Plugin", hint: "Open this panel" };
  if (kind === "file") return { kind: "File", hint: "Open this file" };
  return { kind: "Skill", hint: "Open in Skills" };
}

function KindMark({ kind }: { kind: ChatRefKind | undefined }) {
  if (kind === "pipeline") return <span aria-hidden>🔗</span>;
  if (kind === "ducky" || kind === "profile") {
    return <span className="chat-ref-kind chat-ref-kind--mention" aria-hidden>@</span>;
  }
  const label = kind === "mcp" ? "MCP" : kind === "plugin" ? "Plugin" : kind === "file" ? "File" : kind === "subskill" ? "Subskill" : "Skill";
  return (
    <span className={`chat-ref-kind chat-ref-kind--${kind || "skill"}`} aria-hidden>
      {label.slice(0, 1)}
    </span>
  );
}

export function ChatRefIcon({ href, face, duckyStyle, iconUrl }: {
  href: string;
  face?: ChatRefFace;
  duckyStyle?: string;
  iconUrl?: string;
}) {
  const styleId = duckyStyle || face?.duckyStyle;
  const icon = iconUrl || face?.iconUrl || "";
  if (styleId) return <DuckyAvatar styleId={styleId} size={18} className="chat-ref-avatar" />;
  if (icon && isImageIcon(icon)) return <img src={icon} alt="" draggable={false} />;
  if (icon) return <span className="chat-ref-emoji" aria-hidden>{icon}</span>;
  return <KindMark kind={parseChatRefHref(href)?.kind} />;
}

/** Pill with the ducky or plugin icon. The label is the name, never the markdown. */
export function ChatRefChip({
  href,
  label,
  duckyStyle,
  iconUrl,
  onClick,
}: {
  href: string;
  label: string;
  duckyStyle?: string;
  iconUrl?: string;
  onClick?: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const face = useChatRefFace(href);
  const parsed = parseChatRefHref(href);
  const name = chatRefDisplayName(label) || parsed?.id.split("/").pop() || "reference";
  const tip = refTip(parsed?.kind);
  const tipId = useId();
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const show = (el: HTMLElement) => {
    const box = el.getBoundingClientRect();
    setPos({ x: box.left, y: box.bottom + 6 });
  };
  const hover = {
    onMouseEnter: (event: MouseEvent<HTMLElement>) => show(event.currentTarget),
    onMouseLeave: () => setPos(null),
    onFocus: (event: FocusEvent<HTMLElement>) => show(event.currentTarget),
    onBlur: () => setPos(null),
  };
  const tipNode = pos && typeof document !== "undefined"
    ? createPortal(
        <div id={tipId} role="tooltip" className="rich-ref-tip" style={{ left: pos.x, top: pos.y }}>
          <div className="rich-ref-tip-kind">{tip.kind}</div>
          <div className="rich-ref-tip-name">{name}</div>
          <div className="rich-ref-tip-hint">{tip.hint}</div>
        </div>,
        document.body,
      )
    : null;
  const inner: ReactNode = (
    <>
      <span className="chat-ref-chip-icon">
        <ChatRefIcon href={href} face={face} duckyStyle={duckyStyle} iconUrl={iconUrl} />
      </span>
      <span className="chat-ref-chip-label">{name}</span>
    </>
  );
  if (!onClick) {
    return (
      <span className="chat-ref-chip" aria-describedby={pos ? tipId : undefined} {...hover}>
        {inner}
        {tipNode}
      </span>
    );
  }
  return (
    <>
      <button
        type="button"
        className="chat-ref-chip"
        aria-describedby={pos ? tipId : undefined}
        onMouseDown={(event) => event.stopPropagation()}
        onClick={onClick}
        {...hover}
      >
        {inner}
      </button>
      {tipNode}
    </>
  );
}
