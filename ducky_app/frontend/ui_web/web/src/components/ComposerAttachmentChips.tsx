import type { ComposerAttachment } from "../types/panel";
import { Icons } from "../icons/Icons";

interface ComposerAttachmentChipsProps {
  attachments: ComposerAttachment[];
  onRemove: (id: string) => void;
  /** Open a full-size preview (with drawing tools for images). */
  onPreview?: (att: ComposerAttachment) => void;
  /** Retry a failed video upload. */
  onRetry?: (id: string) => void;
}

function videoStatusLabel(att: Extract<ComposerAttachment, { kind: "video" }>): string {
  if (att.status === "uploading") return "Uploading…";
  if (att.status === "preparing") return `Preparing… ${Math.round((att.progress ?? 0) * 100)}%`;
  if (att.status === "error") return "Error";
  return `${(att.sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ComposerAttachmentChips({ attachments, onRemove, onPreview, onRetry }: ComposerAttachmentChipsProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="composer-attachment-chips">
      {attachments.map((att) => (
        <div key={att.id} className={`composer-attachment-chip composer-attachment-chip--${att.kind}`}>
          <button
            type="button"
            className="composer-attachment-chip-open"
            aria-label={`Preview ${att.name}`}
            title={att.kind === "image" ? "Click to preview / draw" : "Click to preview"}
            onClick={() => onPreview?.(att)}
            disabled={!onPreview}
          >
            {att.kind === "image" ? (
              <img src={att.dataUrl} alt={att.name} className="composer-attachment-chip-thumb" />
            ) : att.kind === "video" ? (
              att.previewUrl ? (
                <video src={att.previewUrl} muted preload="metadata" className="composer-attachment-chip-thumb" />
              ) : (
                <span className="composer-attachment-chip-file-icon" aria-hidden>
                  <Icons.Play />
                </span>
              )
            ) : (
              <span className="composer-attachment-chip-file-icon" aria-hidden>
                <Icons.File />
              </span>
            )}
            <span className="composer-attachment-chip-name" title={att.name}>
              {att.name}
            </span>
            {att.kind === "video" ? (
              <span
                className={`composer-attachment-chip-status is-${att.status}`}
                title={att.status === "error" ? att.error : undefined}
              >
                {videoStatusLabel(att)}
              </span>
            ) : null}
          </button>
          {att.kind === "video" && att.status === "error" && onRetry ? (
            <button
              type="button"
              className="composer-attachment-chip-retry"
              aria-label={`Retry ${att.name}`}
              onClick={() => onRetry(att.id)}
            >
              <Icons.Replay />
            </button>
          ) : null}
          <button
            type="button"
            className="composer-attachment-chip-remove"
            aria-label={`Remove ${att.name}`}
            onClick={() => onRemove(att.id)}
          >
            <Icons.Close />
          </button>
        </div>
      ))}
    </div>
  );
}
