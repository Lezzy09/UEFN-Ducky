import type { DuckyOSStorePatchNote } from "../../../types/panel";
import { formatPatchDate } from "./storeData";

type Props = {
  notes: DuckyOSStorePatchNote[] | null;
};

function NoteRows({ notes }: { notes: DuckyOSStorePatchNote[] }) {
  return (
    <ol className="ds-changelog">
      {notes.map((v) => {
        const date = formatPatchDate(v.created_at);
        return (
          <li key={`${v.version || ""}-${v.created_at || ""}-${v.changelog || ""}`}>
            <span className="ds-changelog-ver">v{v.version || ""}</span>
            {date ? <span className="ds-changelog-date">{date}</span> : null}
            <p className="ds-changelog-note">{v.changelog || "—"}</p>
          </li>
        );
      })}
    </ol>
  );
}

export function PatchNotesList({ notes }: Props) {
  if (notes === null) {
    return (
      <>
        <h3 className="ds-panel-title">Patch notes</h3>
        <p className="ds-panel-desc ds-panel-desc--mute">Loading…</p>
      </>
    );
  }
  if (notes.length === 0) {
    return (
      <>
        <h3 className="ds-panel-title">Patch notes</h3>
        <p className="ds-panel-desc ds-panel-desc--mute">No patch notes yet.</p>
      </>
    );
  }

  return (
    <>
      <h3 className="ds-panel-title">Patch notes</h3>
      <NoteRows notes={[notes[0]!]} />
    </>
  );
}
