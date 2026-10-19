import { useState } from "react";
import type { WhatsNewKind, WhatsNewVersion } from "../types/panel";
import { formatPatchDate } from "../views/settings/store/storeData";
import { DuckyAvatar } from "./ducky/DuckyAvatars";
import { Modal } from "./Modal";
import "./whats-new.css";

const KIND_LABEL: Record<WhatsNewKind, string> = {
  new: "New",
  improved: "Better",
  fix: "Fixed",
};

interface WhatsNewModalProps {
  open: boolean;
  current: string;
  versions: WhatsNewVersion[];
  /** Close with the "Don't show again" choice. */
  onClose: (dontShowAgain: boolean) => void;
  onAllNotes: () => void;
}

/** After an update: each new version's one-line changes, in Ducky's own look. */
export function WhatsNewModal({ open, current, versions, onClose, onAllNotes }: WhatsNewModalProps) {
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const close = () => onClose(dontShowAgain);

  return (
    <Modal
      open={open}
      onClose={close}
      title="What's new"
      hideHeader
      hideClose
      width={500}
      className="whats-new"
      bodyClassName="whats-new-body"
      footer={
        <div className="whats-new-footer">
          <button type="button" className="whats-new-link" onClick={onAllNotes}>
            All patch notes
          </button>
          <label className="whats-new-check">
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(e) => setDontShowAgain(e.target.checked)}
            />
            Don&apos;t show again
          </label>
          <button type="button" className="settings-btn modal-confirm-btn" onClick={close}>
            Got it
          </button>
        </div>
      }
    >
      <div className="whats-new-head">
        <DuckyAvatar size={40} className="whats-new-duck" title="Ducky" />
        <div>
          <h2 className="whats-new-title">What&apos;s new</h2>
          <p className="whats-new-sub">You&apos;re on {current}</p>
        </div>
      </div>
      {versions.map((v) => {
        const date = formatPatchDate(v.created_at);
        return (
          <section key={v.version} className="whats-new-version" aria-label={`Version ${v.version}`}>
            <h3 className="whats-new-version-line">
              {v.version}
              {date ? <span className="whats-new-date"> · {date}</span> : null}
            </h3>
            <ul className="whats-new-list">
              {v.items.map((item) => (
                <li key={`${item.kind}:${item.text}`} className="whats-new-item">
                  <span className={`whats-new-kind whats-new-kind--${item.kind}`}>
                    {KIND_LABEL[item.kind] ?? KIND_LABEL.improved}
                  </span>
                  <span className="whats-new-text">{item.text}</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </Modal>
  );
}
