import type { PluginLiveGroup, PluginScopeStatus } from "../types/panel";
import { groupName, initials, listText, livePeerName, othersHere, personTone, presence, presenceText } from "./scopeBarText";

/** At most this many faces per group; the count says the rest. */
const FACES = 4;

function Face({ name, id }: { name: string; id: string }) {
  return (
    <span className={`plugin-scope-avatar plugin-scope-avatar--tone-${personTone(id)}`} aria-hidden>
      {initials(name)}
    </span>
  );
}

type Props = {
  pluginId: string;
  status: PluginScopeStatus;
  busy: boolean;
  /** Join a teammate's group (its room); none starts this PC's own. */
  onJoin: (room?: string) => void;
  onLeave: () => void;
  /** Follow the host's screen (scroll and tabs) in a group this PC joined. */
  follow: boolean;
  onFollow: (on: boolean) => void;
};

/**
 * The Live dropdown: the plugin's live groups in the team (each named by its host, with who is
 * in it), Join / Leave / End, Follow the host's screen, who else is here but not live, and
 * Start live. People live together see each other's pointers, and what one presses is greyed
 * out for the others.
 */
export function PluginLiveMenu({ pluginId, status, busy, onJoin, onLeave, follow, onFollow }: Props) {
  const live = status.live;
  const groups = live?.groups ?? [];
  const mine = groups.find((g) => g.mine);
  const hosting = Boolean(live?.on && mine?.hostIsMe);
  const plugin = status.pluginLabel || pluginId;
  const idle = othersHere(presence(status.people, pluginId)).filter((row) => !row.live);
  // A peer the provider can't reach, or a group member it has no link to at all.
  const unreached = live?.on
    ? [...new Set([...(live.peers ?? []).filter((p) => p.path === "none").map(livePeerName), ...(live.unlinked ?? [])])]
    : [];
  const connecting = live?.on ? (live.connecting ?? []).filter((name) => !unreached.includes(name)) : [];
  const size = (g: PluginLiveGroup) => `${g.members.length} ${g.members.length === 1 ? "person" : "people"}`;

  return (
    <div className="plugin-scope-menu" role="menu" aria-label={`Live in ${plugin}`}>
      <div className="plugin-scope-menu__head">Live now</div>
      {groups.length ? groups.map((g) => (
        <div key={g.room} className={`plugin-scope-menu__row${g.mine ? " is-mine" : ""}`}>
          <span className="plugin-scope-faces">
            {g.members.slice(0, FACES).map((m) => <Face key={m.device || m.name} name={m.name} id={m.device || m.user || m.name} />)}
          </span>
          <span className="plugin-scope-menu__text">
            <span className="plugin-scope-menu__name">{groupName(g)}</span>
            <span className="plugin-scope-menu__sub">{g.mine ? `${size(g)} · you're in it` : size(g)}</span>
          </span>
          {g.mine ? (
            <button type="button" role="menuitem" className="plugin-scope-btn plugin-scope-btn--row" disabled={busy}
              onClick={onLeave}>
              {g.hostIsMe ? "End" : "Leave"}
            </button>
          ) : (
            <button type="button" role="menuitem" className="plugin-scope-btn plugin-scope-btn--row plugin-scope-btn--primary"
              disabled={busy} aria-label={`Join ${groupName(g)}`} onClick={() => onJoin(g.room)}>
              Join
            </button>
          )}
        </div>
      )) : <div className="plugin-scope-menu__empty">Nobody's live in {plugin} yet.</div>}
      {mine && !mine.hostIsMe && live?.on ? (
        <label className="plugin-scope-menu__row plugin-scope-menu__check-row">
          <input type="checkbox" checked={follow}
            disabled={!mine.members.some((m) => `h:${m.device}` === mine.room)}
            onChange={(event) => onFollow(event.target.checked)} />
          <span className="plugin-scope-menu__text">
            <span className="plugin-scope-menu__name">Follow {groupName(mine)}'s screen</span>
            <span className="plugin-scope-menu__sub">
              {mine.members.some((m) => `h:${m.device}` === mine.room)
                ? "Your view scrolls and switches tabs with theirs."
                : "The host left this group."}
            </span>
          </span>
        </label>
      ) : null}
      {connecting.length ? (
        <div className="plugin-scope-menu__note">Connecting to {listText(connecting)}…</div>
      ) : null}
      {unreached.length ? (
        <div className="plugin-scope-menu__note plugin-scope-menu__note--warn">
          Can't reach {listText(unreached)} on this network, so pointers, Follow and locks don't reach them.
          Changes still sync.
        </div>
      ) : null}
      {idle.length ? (
        <>
          <div className="plugin-scope-menu__sep" />
          <div className="plugin-scope-menu__head">Here, not live</div>
          {idle.map((row) => (
            <div key={row.key} className="plugin-scope-menu__row">
              <span className="plugin-scope-faces"><Face name={row.name} id={row.id} /></span>
              <span className="plugin-scope-menu__text">
                <span className="plugin-scope-menu__name">{row.self ? `You on ${row.device}` : row.name}</span>
                <span className="plugin-scope-menu__sub">{[row.device, presenceText(row, plugin)].filter(Boolean).join(" · ")}</span>
              </span>
            </div>
          ))}
        </>
      ) : null}
      {!hosting ? (
        <>
          <div className="plugin-scope-menu__sep" />
          <div className="plugin-scope-menu__foot">
            <button type="button" role="menuitem" className="plugin-scope-btn plugin-scope-btn--block" disabled={busy}
              onClick={() => onJoin()}>
              Start live
            </button>
          </div>
        </>
      ) : null}
      <div className="plugin-scope-menu__note">
        People live together see each other's pointers and can follow the host's screen. What anyone presses is locked
        for the others until they're done.
      </div>
    </div>
  );
}
