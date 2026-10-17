import { useState } from "react";
import "./plugin-ui.css";
import { Modal, ModalActions } from "../components/Modal";
import type { PluginFolderShareUnit } from "../types/panel";
import { FOLDER_NOTE, firstShareText, pickedText, unitSizeText } from "./scopeBarText";

type Props = {
  /** The plugin's display name. */
  plugin: string;
  team: string;
  /** The Local copy's units, with their sizes. */
  units: PluginFolderShareUnit[];
  note?: string;
  /** The team has some of the files already ("Copy Local into"): the units listed are the rest. */
  partial?: boolean;
  busy?: boolean;
  onShare: (units: string[]) => void;
  onStartEmpty: () => void;
  onCancel: () => void;
};

/**
 * The first share of a plugin's folders into a team that has none of its files yet (or,
 * `partial`, the units it lacks): which Local units to copy (with their sizes), and that
 * the files stay plaintext on each PC. Picking none shares nothing until the person says
 * Start empty (Copy nothing, when the team has files).
 */
export function FolderShareDialog({ plugin, team, units, note, partial = false, busy = false, onShare, onStartEmpty,
  onCancel }: Props) {
  const [picked, setPicked] = useState(() => new Set(units.map((unit) => unit.unit)));
  const ask = firstShareText(plugin, team, partial);
  const toggle = (unit: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(unit)) next.delete(unit);
      else next.add(unit);
      return next;
    });

  return (
    <Modal
      open
      onClose={onCancel}
      title={ask.title}
      width={460}
      footer={
        <ModalActions
          cancelLabel="Cancel"
          extraLabel={partial ? "Copy nothing" : "Start empty"}
          confirmLabel="Copy and share"
          confirmDisabled={busy || picked.size === 0}
          onCancel={onCancel}
          onExtra={() => { if (!busy) onStartEmpty(); }}
          onConfirm={() => { if (!busy && picked.size) onShare(units.filter((u) => picked.has(u.unit)).map((u) => u.unit)); }}
        />
      }
    >
      <div className="plugin-folder-share">
        <p className="confirm-modal-message">{ask.message}</p>
        {units.length ? (
          <fieldset className="plugin-folder-share__units">
            <legend className="sr-only">Units to copy into {team}</legend>
            {units.map((unit) => {
              const size = unitSizeText(unit.files, unit.bytes);
              return (
                <label key={`${unit.folder ?? ""}:${unit.unit}`} className="plugin-folder-share__unit">
                  <input type="checkbox" checked={picked.has(unit.unit)} disabled={busy} onChange={() => toggle(unit.unit)} />
                  <span className="plugin-folder-share__name">{unit.name}</span>
                  {size ? <span className="plugin-folder-share__size">{size}</span> : null}
                </label>
              );
            })}
          </fieldset>
        ) : (
          <p className="confirm-modal-message">Your Local copy is empty.</p>
        )}
        {units.length ? <p className="plugin-folder-share__picked">{pickedText(units, picked)}</p> : null}
        <p className="confirm-modal-message">{note || FOLDER_NOTE}</p>
      </div>
    </Modal>
  );
}
