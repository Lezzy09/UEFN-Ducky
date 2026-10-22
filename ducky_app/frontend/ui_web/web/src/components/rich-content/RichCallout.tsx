import { Icons } from "../../icons/Icons";
import type { OpenFileHandler, RichCalloutTone } from "../../types/richContent";
import { RichCodeBlock } from "./RichCodeBlock";
import { RichInline } from "./RichInline";

interface RichCalloutProps {
  tone: RichCalloutTone;
  text: string;
  title?: string;
  onOpenFile?: OpenFileHandler;
}

function CalloutIcon({ tone }: { tone: RichCalloutTone }) {
  if (tone === "success") return <Icons.Check />;
  if (tone === "error") return <Icons.ErrorCircle />;
  if (tone === "info") return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7h.01" />
    </svg>
  );
  return <Icons.AlertTriangle />;
}

export function RichCallout({ tone, text, title, onOpenFile }: RichCalloutProps) {
  const label = title || { info: "Note", warn: "Warning", error: "Error", success: "Verified" }[tone];
  return (
    <div className={`rich-callout rich-callout--${tone}`}>
      <div className="rich-callout-title">
        <CalloutIcon tone={tone} />
        {label}
      </div>
      <div className="rich-callout-body">
        {calloutParts(text).map((part, i) =>
          part.code != null ? (
            <RichCodeBlock key={i} text={part.code} language={part.language} />
          ) : (
            <RichInline key={i} text={part.text} onOpenFile={onOpenFile} />
          ),
        )}
      </div>
    </div>
  );
}

/** A fenced block in a callout is a code block of its own, never one inline chip holding
 *  every line (a "push from your terminal" tip showed both commands as one centred name). */
function calloutParts(text: string): Array<{ text: string; code?: string; language?: string }> {
  const out: Array<{ text: string; code?: string; language?: string }> = [];
  const fence = /```([\w+#.-]*)[^\S\n]*\n([\s\S]*?)\n?```/g;
  let at = 0;
  for (const m of text.matchAll(fence)) {
    const before = text.slice(at, m.index).trim();
    if (before) out.push({ text: before });
    out.push({ text: "", code: m[2], language: m[1] || undefined });
    at = (m.index ?? 0) + m[0].length;
  }
  const rest = text.slice(at).trim();
  if (rest || !out.length) out.push({ text: rest });
  return out;
}
