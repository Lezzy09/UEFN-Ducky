// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FINISH_TEAM_PROMPT, FinishTeamCard, parseFinishTeam } from "./FinishTeamCard";
import { SWARM_CARD_EVENT } from "./SwarmCard";

const card = JSON.stringify({
  ok: true,
  ui: "finish_team",
  status: "needs_confirm",
  plan_title: "Swarm speed",
  lead: "lead",
  seats: [
    { conv_id: "a", name: "Builder", commits: ["c1", "c2"], dirty: [] },
    { conv_id: "b", name: "Tester", commits: ["c3"], dirty: ["src/b/x.py"] },
  ],
  totals: { seats: 2, commits: 3, uncommitted: 1 },
});

afterEach(cleanup);

describe("FinishTeamCard", () => {
  it("lists each seat's commits and uncommitted files", () => {
    render(<FinishTeamCard resultText={card} />);
    expect(screen.getByText("Finish team: 2 seats · 3 commits · 1 uncommitted")).toBeTruthy();
    expect(screen.getByText("(c1, c2)")).toBeTruthy();
    expect(screen.getByLabelText("Tester uncommitted").textContent).toBe("src/b/x.py");
    expect(screen.queryByLabelText("Builder uncommitted")).toBeNull();
  });

  it("Archive team sends the confirm line", () => {
    const onSend = vi.fn();
    render(<FinishTeamCard resultText={card} onSend={onSend} />);
    fireEvent.click(screen.getByRole("button", { name: "Archive team" }));
    expect(onSend).toHaveBeenCalledWith(FINISH_TEAM_PROMPT);
  });

  it("without onSend the line bubbles to the chat pane", () => {
    const seen: string[] = [];
    const host = document.createElement("div");
    document.body.appendChild(host);
    host.addEventListener(SWARM_CARD_EVENT, (e) => seen.push((e as CustomEvent<{ text: string }>).detail.text));
    render(<FinishTeamCard resultText={card} />, { container: host });
    fireEvent.click(screen.getByRole("button", { name: "Archive team" }));
    expect(seen).toEqual([FINISH_TEAM_PROMPT]);
    host.remove();
  });

  it("done shows what was archived, with no button", () => {
    render(<FinishTeamCard resultText={JSON.stringify({ ok: true, ui: "finish_team", status: "done", archived: ["a", "b"], terminals_closed: ["t1"] })} />);
    expect(screen.getByText("Team archived: 2 seats · 1 terminals closed")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("ignores other results", () => {
    expect(parseFinishTeam("not json")).toBeNull();
    expect(parseFinishTeam(JSON.stringify({ ui: "swarm_builder", status: "needs_confirm" }))).toBeNull();
  });
});
