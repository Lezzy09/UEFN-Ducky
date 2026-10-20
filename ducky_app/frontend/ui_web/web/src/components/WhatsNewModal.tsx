import type { WhatsNewKind, WhatsNewVersion } from "../types/panel";
import { formatPatchDate } from "../views/settings/store/storeData";
import { DuckyAvatar } from "./ducky/DuckyAvatars";
import { Modal, ModalActions } from "./Modal";
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
  onClose: () => void;
}

/** After an update: each new version's one-line changes, in Ducky's own modal. */
export function WhatsNewModal({ open, current, versions, onClose }: WhatsNewModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="What's new"
      width={500}
      className="whats-new"
      bodyClassName="whats-new-body"
      footer={<ModalActions onCancel={onClose} onConfirm={onClose} confirmLabel="Got it" hideCancel />}
    >
      <div className="whats-new-head">
        <DuckyAvatar size={32} className="whats-new-duck" title="Ducky" />
        <p className="whats-new-sub">You&apos;re on {current}</p>
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
