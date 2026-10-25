import { useMemo, useRef } from "react";
import { SWARM_CARD_EVENT } from "./SwarmCard";

// ducky_finish_team results: the lead's "Finish team" card. needs_confirm lists each
// seat's commits and uncommitted files with one Archive team button; done says what was
// archived. The button only sends a chat line; the tool's own Yes/No asks the person.

export interface FinishTeamSeat {
  conv_id: string;
  name: string;
  commits: string[];
  dirty: string[];
}

export interface FinishTeamData {
  status: "needs_confirm" | "done";
  planTitle: string;
  seats: FinishTeamSeat[];
  archived: string[];
  terminalsClosed: number;
}

export const FINISH_TEAM_PROMPT = "Finish the team: call ducky_finish_team with confirm=true.";

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/** The card's data from a ducky_finish_team result, or null when it isn't one. */
export function parseFinishTeam(text: string): FinishTeamData | null {
  let raw: unknown;
  try {
    raw = JSON.parse(text.trim());
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (obj.ui !== "finish_team" || (obj.status !== "needs_confirm" && obj.status !== "done")) return null;
  const seats = (Array.isArray(obj.seats) ? obj.seats : []).flatMap((s): FinishTeamSeat[] => {
    if (!s || typeof s !== "object") return [];
    const seat = s as Record<string, unknown>;
    const id = typeof seat.conv_id === "string" ? seat.conv_id : "";
    return [{ conv_id: id, name: typeof seat.name === "string" && seat.name ? seat.name : id, commits: strings(seat.commits), dirty: strings(seat.dirty) }];
  });
  return {
    status: obj.status,
    planTitle: typeof obj.plan_title === "string" ? obj.plan_title : "",
    seats,
    archived: strings(obj.archived),
    terminalsClosed: strings(obj.terminals_closed).length,
  };
}

export function finishTeamSummary(data: FinishTeamData): string {
  const commits = data.seats.reduce((n, s) => n + s.commits.length, 0);
  const dirty = data.seats.reduce((n, s) => n + s.dirty.length, 0);
  return `Finish team: ${data.seats.length} seats · ${commits} commits · ${dirty} uncommitted`;
}

export interface FinishTeamCardProps {
  resultText?: string;
  onSend?: (text: string) => void;
}

export function FinishTeamCard({ resultText = "", onSend }: FinishTeamCardProps) {
  const cardRef = useRef<HTMLElement>(null);
  const data = useMemo(() => parseFinishTeam(resultText), [resultText]);
  if (!data) return null;
  const send = (text: string) => {
    if (onSend) onSend(text);
    else cardRef.current?.dispatchEvent(new CustomEvent(SWARM_CARD_EVENT, { detail: { action: "finish", text }, bubbles: true }));
  };

  if (data.status === "done") {
    const title = `Team archived: ${data.archived.length} seats · ${data.terminalsClosed} terminals closed`;
    return (
      <section ref={cardRef} className="swarm-card finish-team-card finish-team-card--done" aria-label={title}>
        <header className="swarm-card-title">{title}</header>
      </section>
    );
  }

  const summary = finishTeamSummary(data);
  return (
    <section ref={cardRef} className="swarm-card finish-team-card" aria-label={summary}>
      <header className="swarm-card-title">{summary}</header>
      {data.planTitle ? <div className="swarm-card-summary">{data.planTitle}</div> : null}
      <ul className="finish-team-seats">
        {data.seats.map((s) => (
          <li key={s.conv_id} className="finish-team-seat">
            <strong>{s.name}</strong>
            {` · ${s.commits.length} commit${s.commits.length === 1 ? "" : "s"}`}
            {s.commits.length ? <span className="finish-team-commits"> ({s.commits.join(", ")})</span> : null}
            {s.dirty.length ? (
              <ul className="finish-team-dirty" aria-label={`${s.name} uncommitted`} style={{ color: "var(--red)" }}>
                {s.dirty.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="swarm-card-actions">
        <button type="button" className="swarm-card-btn swarm-card-btn--primary" onClick={() => send(FINISH_TEAM_PROMPT)}>
          Archive team
        </button>
      </div>
    </section>
  );
}

/** For TOOL_VIEWS (resolveToolPresenter): the card from a tool result. */
export function FinishTeamToolView({ resultText }: { resultText: string }) {
  return <FinishTeamCard resultText={resultText} />;
}
