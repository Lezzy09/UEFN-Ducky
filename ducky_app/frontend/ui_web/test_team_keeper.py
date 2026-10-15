"""The keeper wakes an idle team's coordinator, backs off when a wake starts no work."""

from __future__ import annotations

import pytest

from frontend.ui_web import team_keeper as keeper

MIN = 60.0
PLAN = {"chat_id": "coord", "status": "open", "progress": {"pending": 3, "in_progress": 1, "completed": 2}}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    keeper.reset_for_tests()
    monkeypatch.setattr(keeper, "_tell_person", lambda cid, minutes: None)
    saved: dict[str, str] = {}  # stands in for the app database across "restarts"
    monkeypatch.setattr(keeper, "_load_parked", lambda cid: saved.get(cid))
    monkeypatch.setattr(keeper, "_save_parked",
                        lambda cid, moves: saved.pop(cid, None) if moves is None else saved.__setitem__(cid, moves))
    yield saved
    keeper.reset_for_tests()


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    """Members are the owners themselves, nobody is blocked, the broker allows work."""
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(keeper, "_member_chat", lambda owner, root: owner)
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: "")
    monkeypatch.setattr(keeper, "_tell_lead", lambda plan, member, work, reason: told.append((member, reason)))
    return told


@pytest.fixture(autouse=True)
def _links(monkeypatch):
    """Who each started member runs under, and the person's "team waits on you" alerts."""
    seen: dict[str, list] = {"links": [], "waiting": []}
    monkeypatch.setattr(keeper, "_inherit_lead", lambda member, lead: seen["links"].append((member, lead)))
    monkeypatch.setattr(keeper, "_alert_waiting", lambda lead: seen["waiting"].append(lead))
    return seen


SUB = {**PLAN, "id": "p1", "title": "Ship it", "nodes": [
    {"id": "sec", "content": "Effects", "assignee": "builder", "status": "in_progress",
     "body_markdown": "Files: fx.py", "children": [
         {"id": "fx", "content": "Glow", "status": "in_progress", "body_markdown": "Done when: glow test passes"},
         {"id": "blur", "content": "Blur", "status": "pending"}]},
    {"id": "later", "content": "Ship", "assignee": "builder2", "status": "pending", "after": ["sec"]},
]}


def _run(now: float, running: list[str], woke: list[tuple[str, str]], plans=None) -> list[str]:
    return keeper.tick(
        now=now,
        plans=[PLAN] if plans is None else plans,
        running=running,
        wake=lambda cid, text: woke.append((cid, text)),
    )


def test_a_quiet_team_with_open_work_wakes_its_coordinator() -> None:
    woke: list[tuple[str, str]] = []
    assert _run(0, ["builder"], woke) == []  # working
    assert _run(1 * MIN, [], woke) == []  # quiet for 1 minute: not yet
    assert _run(2 * MIN, [], woke) == ["coord"]
    assert "4 open steps" in woke[0][1] and "2 minutes" in woke[0][1]


def test_wakes_that_start_no_work_back_off_then_park_and_real_work_resets_it() -> None:
    woke: list[tuple[str, str]] = []
    times = []
    for minute in range(0, 240):
        if _run(minute * MIN, [], woke):
            times.append(minute)
    # Waits 2, then 4 minutes; three wakes that moved nothing park it (no hourly wakes
    # forever for a plan whose last open step is the user's).
    assert times == [2, 4, 8]
    # The coordinator answering on its own is not progress: it stays parked.
    _run(240 * MIN, ["coord"], woke)
    assert _run(300 * MIN, [], woke) == []
    # A member working is progress: the next wake is 2 quiet minutes away again.
    _run(301 * MIN, ["builder"], woke)
    assert _run(302 * MIN, [], woke) == []
    assert _run(303 * MIN, [], woke) == ["coord"]


def test_a_step_that_moves_unparks_the_keeper() -> None:
    woke: list[tuple[str, str]] = []
    plan = {**PLAN, "nodes": [{"id": "s1", "content": "Build", "status": "in_progress"}, {"id": "s2", "content": "Ship", "status": "pending"}]}
    times = [m for m in range(0, 120) if _run(m * MIN, [], woke, plans=[plan])]
    assert times == [2, 4, 8]
    # The user ticks a step (or hands it to someone): the team has news, so it wakes again.
    moved = {**plan, "nodes": [{"id": "s1", "content": "Build", "status": "completed"}, {"id": "s2", "content": "Ship", "status": "pending"}]}
    assert _run(120 * MIN, [], woke, plans=[moved]) == ["coord"]
    # A note alone is not a move.
    noted = {**moved, "nodes": [{"id": "s1", "content": "Build", "status": "completed", "body_markdown": "x"}, {"id": "s2", "content": "Ship", "status": "pending"}]}
    later = [m for m in range(121, 240) if _run(m * MIN, [], woke, plans=[noted])]
    assert later == [122, 126]  # 2 and 4 minutes on, then parked again


def test_any_running_agent_keeps_the_keeper_quiet() -> None:
    woke: list[tuple[str, str]] = []
    for minute in range(0, 19):  # 20 busy minutes with no finished step is a circle (below)
        _run(minute * MIN, ["someone"], woke)
    assert woke == []


def test_only_started_open_team_plans_are_kept(monkeypatch) -> None:
    rows = [
        {**PLAN, "chat_id": "coord"},
        {**PLAN, "chat_id": "paused", "status": "paused"},
        {**PLAN, "chat_id": "finished", "status": "finished"},
        {**PLAN, "chat_id": "unstarted", "progress": {"pending": 5}},
        {**PLAN, "chat_id": "done", "progress": {"completed": 5}},
        {**PLAN, "chat_id": "solo"},  # not the leader of any group
    ]
    import backend.agent.coding_agents.plans as plans

    monkeypatch.setattr(plans, "list_plans", lambda project_root=None: rows)
    monkeypatch.setattr(keeper, "_project_roots", lambda root: ["C:/island"])
    monkeypatch.setattr(
        keeper, "_team_leaders", lambda root: {"coord", "paused", "finished", "unstarted", "done"}
    )
    assert [p["chat_id"] for p in keeper.kept_plans()] == ["coord"]


def test_archived_and_dormant_team_plans_are_left_alone(monkeypatch) -> None:
    # Oct 12 2026: scanning recent projects woke six chats of three earlier teams at once.
    import time

    import backend.agent.coding_agents.plans as plans

    now = time.time()
    rows = [
        {**PLAN, "chat_id": "live", "updated_at": now - 600},
        {**PLAN, "chat_id": "archived", "status": "archived", "updated_at": now - 600},
        {**PLAN, "chat_id": "old", "updated_at": now - 3 * 3600},
    ]
    monkeypatch.setattr(plans, "list_plans", lambda project_root=None: rows)
    monkeypatch.setattr(keeper, "_project_roots", lambda root: ["C:/island"])
    monkeypatch.setattr(keeper, "_team_leaders", lambda root: {"live", "archived", "old"})
    assert [p["chat_id"] for p in keeper.kept_plans()] == ["live"]


def test_a_failed_wake_is_retried_next_tick() -> None:
    calls: list[str] = []

    def _boom(cid: str, text: str) -> None:
        calls.append(cid)
        raise RuntimeError("panel busy")

    keeper.tick(now=0, plans=[PLAN], running=[], wake=_boom)
    assert keeper.tick(now=2 * MIN, plans=[PLAN], running=[], wake=_boom) == []
    assert keeper.tick(now=11 * MIN, plans=[PLAN], running=[], wake=lambda c, t: None) == ["coord"]
    assert calls == ["coord"]


@pytest.mark.parametrize("stopped", [False, True])
def test_keeper_respects_broker_cooldown_and_explicit_stop(monkeypatch, stopped):
    from backend.agent import a2a_broker as broker
    monkeypatch.setattr(broker, "_stopped", set(), raising=False)
    monkeypatch.setattr(broker, "_cooldowns", {}, raising=False)
    monkeypatch.setattr(broker, "_held", {}, raising=False)
    monkeypatch.setattr(broker, "_uncertain_chats", set(), raising=False)
    monkeypatch.setattr(broker, "_account_key", lambda cid: "test-account", raising=False)
    monkeypatch.setattr(broker, "_retry_queue_later", lambda cid: None)
    monkeypatch.setattr(broker, "send_notice", lambda **kw: None)
    if stopped:
        broker.on_agent_cancelled_by_user("coord")
    else:
        broker.on_agent_stopped("coord", "error", detail='{"error":{"type":"rate_limit_error"}}')
    woke = []
    assert _run(0, [], woke) == []
    assert _run(2 * MIN, [], woke) == []
    assert _run(20 * MIN, [], woke) == []
    assert woke == []


def test_two_minute_wake_names_work_members_and_reports(monkeypatch):
    from types import SimpleNamespace
    from frontend.ui_web import project_chats
    from backend.agent.coding_agents import plans
    monkeypatch.setattr(project_chats, "list_all_conversation_metadata", lambda _: [SimpleNamespace(id="builder", title="Builder", is_group=False)])
    monkeypatch.setattr(plans, "_chat_and_group_ids", lambda cid, root: [cid, "group-a"])
    plan = {**PLAN, "nodes": [{"id": "section", "content": "Modes", "assignee": "group-a", "children": [
        {"id": "next", "content": "Next adapter", "status": "pending"}]}],
        "team_reports": [{"body": "Builder completed previous adapter"}]}
    monkeypatch.setattr(keeper, "_member_chat", lambda owner, root: "")  # no chat can take the work
    woke = []
    assert _run(0, ["unrelated"], woke, [plan]) == []
    assert _run(119, ["unrelated"], woke, [plan]) == []
    assert _run(120, ["unrelated"], woke, [plan]) == ["coord"]
    assert all(t in woke[0][1] for t in ["Next adapter (next)", "Builder (builder)", "completed previous adapter"])
    assert _run(240, ["builder"], woke, [plan]) == []
    assert _run(359, [], woke, [plan]) == []
    assert _run(360, [], woke, [plan]) == ["coord"]


def test_a_parked_team_stays_parked_after_the_app_restarts(_fresh) -> None:
    # Each app start used to allow three more wakes of a plan waiting on the user.
    woke: list[tuple[str, str]] = []
    assert [m for m in range(0, 60) if _run(m * MIN, [], woke)] == [2, 4, 8]
    assert "coord" in _fresh
    keeper.reset_for_tests()  # the app restarts; the database keeps the parking
    assert [m for m in range(60, 200) if _run(m * MIN, [], woke)] == []
    # A member working after the restart unparks it, in memory and in the database.
    _run(200 * MIN, ["builder"], woke)
    assert "coord" not in _fresh
    assert _run(202 * MIN, [], woke) == ["coord"]


def test_a_busy_team_that_finishes_nothing_gets_one_circle_notice_per_20_minutes(monkeypatch) -> None:
    # Oct 11 2026: six agents worked for an hour, sent 292 messages and finished no step.
    told: list[int] = []
    monkeypatch.setattr(keeper, "_tell_person", lambda cid, minutes: told.append(minutes))
    woke: list[tuple[str, str]] = []
    times = [m for m in range(0, 50) if _run(m * MIN, ["builder"], woke)]
    assert times == [20, 40]
    assert "20 minutes and no plan step has finished (2 of 6 done)" in woke[0][1]
    assert "ask the person with ducky_ask_user" in woke[0][1] and "Don't message members" in woke[0][1]
    assert told == [20, 40]


def test_a_finished_step_restarts_the_circle_clock() -> None:
    woke: list[tuple[str, str]] = []
    for minute in range(0, 15):
        _run(minute * MIN, ["builder"], woke)
    progressed = {**PLAN, "progress": {"pending": 3, "in_progress": 0, "completed": 3}}
    later = [m for m in range(15, 50) if _run(m * MIN, ["builder"], woke, plans=[progressed])]
    assert later == [35]  # 20 minutes after the step finished at minute 15


def test_each_member_gets_its_sub_plan_as_one_task_and_the_lead_waits(monkeypatch) -> None:
    # Oct 12 2026 owner: leads dispatched, resumed and chased members by message; members
    # reported back and waited. Like sub-agents, each member now gets its sub plan as one task.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[SUB])
    assert [cid for cid, _ in woke] == ["builder"]  # builder2's step waits for the sub plan "sec"
    task = woke[0][1]
    assert "sub plan “Effects” in the plan “Ship it”" in task and "Files: fx.py" in task
    assert "`fx` Glow (in_progress)" in task and "Done when: glow test passes" in task
    assert "`blur` Blur (pending)" in task and "BLOCKED:" in task and "no messages" in task
    for minute in range(1, 15):
        _run(minute * MIN, ["builder"], woke, plans=[SUB])  # working: no nudges, no lead wake
    assert [cid for cid, _ in woke] == ["builder"]


def test_a_member_whose_turn_ends_with_points_left_is_started_again(monkeypatch) -> None:
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    woke: list[tuple[str, str]] = []
    member = lambda: [cid for cid, _ in woke if cid == "builder"]  # noqa: E731
    _run(0, [], woke, plans=[SUB])
    _run(60, ["builder"], woke, plans=[SUB])
    _run(120, [], woke, plans=[SUB])  # its turn ended
    _run(200, [], woke, plans=[SUB])
    assert member() == ["builder"]  # idle 80 s: not yet
    _run(215, [], woke, plans=[SUB])
    assert member() == ["builder", "builder"]
    assert "Points left in your sub plan “Effects”" in woke[-1][1] and "`blur` Blur (pending)" in woke[-1][1]
    for minute in range(4, 40):
        _run(minute * MIN, [], woke, plans=[SUB])
    assert len(member()) == 3  # started again twice, then it waits for the plan to move
    assert "coord" in [cid for cid, _ in woke]  # nothing can move on its own: now the lead decides
    moved = {**SUB, "nodes": [{**SUB["nodes"][0], "children": [
        {**SUB["nodes"][0]["children"][0], "status": "completed"}, SUB["nodes"][0]["children"][1]]},
        SUB["nodes"][1]]}
    _run(41 * MIN, [], woke, plans=[moved])
    assert len(member()) == 4


def test_a_blocked_member_is_left_alone_and_its_lead_told_once(monkeypatch, _world) -> None:
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    said = {"text": ""}
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: said["text"])
    woke: list[tuple[str, str]] = []
    member = lambda: [cid for cid, _ in woke if cid == "builder"]  # noqa: E731
    _run(0, [], woke, plans=[SUB])
    said["text"] = "the panel capture of revision 45"
    for minute in range(1, 8):
        _run(minute * MIN, [], woke, plans=[SUB])
    assert _world == [("builder", "the panel capture of revision 45")]
    assert member() == ["builder"]  # no "continue" nudges for a blocked member
    assert "coord" not in [cid for cid, _ in woke]  # the notice is the lead's wake
    # The lead changed the plan: the member goes on, and the same block is not told again.
    moved = {**SUB, "nodes": [*SUB["nodes"], {"id": "cap", "content": "Capture", "assignee": "builder2",
                                              "status": "completed"}]}
    _run(10 * MIN, [], woke, plans=[moved])
    assert member() == ["builder", "builder"]
    assert len(_world) == 1


def test_a_member_blocked_again_goes_to_the_person_not_the_lead(monkeypatch, _world) -> None:
    # Oct 12 2026: a lead answered each block with one more step asking for the same live-panel
    # evidence; the worker blocked again, and the lead was woken again, for an hour.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(keeper, "_ask_person", lambda plan, member, work, reason: asked.append((member, reason)))
    said = {"text": ""}
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: said["text"])
    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[SUB])
    said["text"] = "need the live panel on screen"
    _run(1 * MIN, [], woke, plans=[SUB])
    assert _world == [("builder", "need the live panel on screen")] and asked == []
    # The lead added a step; the member goes on, finishes nothing and blocks on it again.
    moved = {**SUB, "nodes": [{**SUB["nodes"][0], "children": [*SUB["nodes"][0]["children"],
             {"id": "again", "content": "Capture the live panel", "status": "pending"}]}, SUB["nodes"][1]]}
    _run(5 * MIN, [], woke, plans=[moved])
    said["text"] = "still need the live panel on screen"
    for minute in range(7, 40):
        _run(minute * MIN, [], woke, plans=[moved])
    assert asked == [("builder", "still need the live panel on screen")]
    assert len(_world) == 1  # the lead was not told a second time
    assert "coord" not in [cid for cid, _ in woke]  # and not woken for it either


def test_members_run_under_their_leads_approvals(monkeypatch, _links) -> None:
    # Oct 15 2026: Ducky started members with no "started by" link, so a lead's Allow everything
    # never reached them and a member's test command waited on a card nobody saw.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[SUB])  # its task
    _run(60, ["builder"], woke, plans=[SUB])
    _run(120, [], woke, plans=[SUB])  # its turn ended with points left
    _run(215, [], woke, plans=[SUB])  # idle 95 s: continue
    assert [cid for cid, _ in woke] == ["builder", "builder"]
    assert _links["links"] == [("builder", "coord"), ("builder", "coord")]


def test_a_lead_that_rewrites_a_blocked_point_starts_the_member_again(monkeypatch, _world, _links) -> None:
    # Oct 15 2026: the lead answered a block by rewriting the member's point without changing its
    # status; that was "no change", so the member never ran again and the team sat idle.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    said = {"text": ""}
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: said["text"])
    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[SUB])
    said["text"] = "ducky_terminal_run approval timed out"
    _run(1 * MIN, [], woke, plans=[SUB])
    assert _world == [("builder", "ducky_terminal_run approval timed out")]
    point = SUB["nodes"][0]["children"][0]
    rewritten = {**SUB, "nodes": [{**SUB["nodes"][0], "children": [
        {**point, "body_markdown": "Run the tests once more: approvals are fixed."},
        SUB["nodes"][0]["children"][1]]}, SUB["nodes"][1]]}
    _run(3 * MIN, [], woke, plans=[rewritten])
    assert [cid for cid, _ in woke] == ["builder", "builder"]
    assert "Points left" in woke[-1][1]


def test_a_team_left_waiting_after_its_lead_had_the_block_tells_the_person_once(monkeypatch, _world, _links) -> None:
    # The lead heard of the block and ended its turn without changing the plan: nothing can
    # move until the person acts, and before this nobody told them.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"builder", "builder2"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    said = {"text": ""}
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: said["text"])
    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[SUB])
    said["text"] = "need the person's login"
    _run(1 * MIN, [], woke, plans=[SUB])
    _run(2 * MIN, ["coord"], woke, plans=[SUB])  # the lead's turn on the block notice
    _run(3 * MIN, [], woke, plans=[SUB])
    assert _links["waiting"] == []  # it only just ended
    for minute in range(4, 30):
        _run(minute * MIN, [], woke, plans=[SUB])
    assert _links["waiting"] == ["coord"]  # once, after two quiet minutes
    assert [cid for cid, _ in woke] == ["builder"]  # nobody woken in a loop


def test_a_block_said_while_waiting_on_a_teammate_is_over_when_the_teammate_finishes(monkeypatch, _world) -> None:
    # Oct 15 2026: the reports member finished its first point and ended "BLOCKED: needs the CLI"
    # while its second point waited on the CLI. When the CLI was done, Ducky read that old line
    # as a new block, told the lead, and parked the member.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"reports", "cli"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    said = {"text": ""}
    monkeypatch.setattr(keeper, "_blocked_reason", lambda member: said["text"] if member == "reports" else "")

    def ledger(r1: str, cli: str) -> dict:
        return {**PLAN, "id": "p3", "title": "Ledger", "nodes": [
            {"id": "cli", "content": "CLI", "assignee": "cli", "status": cli},
            {"id": "reports", "content": "Reports", "assignee": "reports", "status": "in_progress", "children": [
                {"id": "r1", "content": "Text reports", "status": r1},
                {"id": "r2", "content": "CSV report option", "status": "pending", "after": ["cli"]}]}]}

    woke: list[tuple[str, str]] = []
    _run(0, [], woke, plans=[ledger("pending", "in_progress")])
    _run(60, ["reports", "cli"], woke, plans=[ledger("pending", "in_progress")])
    said["text"] = "r2 needs the CLI owner to finish cli.py"
    for minute in range(2, 6):  # r1 done; r2 waits on the CLI, which is still being built
        _run(minute * MIN, ["cli"], woke, plans=[ledger("completed", "in_progress")])
    for minute in range(6, 10):  # the CLI is done: r2 can start
        _run(minute * MIN, [], woke, plans=[ledger("completed", "completed")])
    assert _world == []  # the lead heard of no block
    assert [cid for cid, text in woke if cid == "reports"][-1] == "reports"
    assert "`r2` CSV report option" in [text for cid, text in woke if cid == "reports"][-1]


def test_a_group_leader_with_its_own_sub_plan_gets_one_task(monkeypatch, _links) -> None:
    # The group's sub plan goes to the group's leader, who also owns a sub plan of its own:
    # two owners, one chat. The task used to switch between them on every tick.
    monkeypatch.setattr(keeper, "_team_context", lambda plan: ({"leader"}, ""))
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: False)
    monkeypatch.setattr(keeper, "_member_chat", lambda owner, root: "leader" if owner in ("core", "leader") else owner)
    plan = {**PLAN, "id": "p2", "title": "Ledger", "nodes": [
        {"id": "core", "content": "Core", "assignee": "core", "status": "pending", "children": [
            {"id": "setup", "content": "Package setup", "status": "pending"},
            {"id": "models", "content": "Models", "assignee": "leader", "status": "pending", "children": [
                {"id": "m1", "content": "Transaction", "status": "pending"}]}]}]}
    woke: list[tuple[str, str]] = []
    for minute in range(0, 12):
        _run(minute * MIN, [], woke, plans=[plan])
    tasks = [text for cid, text in woke if cid == "leader" and "Your task" in text]
    assert len(tasks) == 1
    assert "`setup` Package setup" in tasks[0] and "`m1` Transaction" in tasks[0]
    assert len([cid for cid, _ in woke if cid == "leader"]) <= 3  # its task, then two continues at most


def test_a_lead_with_members_but_no_assignments_yet_is_kept(monkeypatch) -> None:
    # A lead whose turn ended after writing the plan and seating its members, before giving any
    # sub plan an owner, was never woken.
    import backend.agent.coding_agents.plans as plans

    rows = [{**PLAN, "chat_id": "staffed", "progress": {"pending": 5}},
            {**PLAN, "chat_id": "alone", "progress": {"pending": 5}}]
    monkeypatch.setattr(plans, "list_plans", lambda project_root=None: rows)
    monkeypatch.setattr(keeper, "_project_roots", lambda root: ["C:/island"])
    monkeypatch.setattr(keeper, "_team_leaders", lambda root: {"staffed", "alone"})
    monkeypatch.setattr(keeper, "_staffed_leaders", lambda root: {"staffed"})
    assert [p["chat_id"] for p in keeper.kept_plans()] == ["staffed"]


def test_a_stopped_builder_is_not_woken(monkeypatch) -> None:
    monkeypatch.setattr("backend.agent.a2a_broker.automatic_work_blocked", lambda cid, **kw: cid == "builder")
    plan = {**PLAN, "nodes": [{"id": "fx", "content": "Effects", "status": "in_progress", "assignee": "builder"}]}
    woke: list[tuple[str, str]] = []
    for minute in range(0, 10):
        _run(minute * MIN, ["coord"], woke, plans=[plan])
    assert [cid for cid, _ in woke if cid == "builder"] == []


def test_a_team_in_another_project_is_kept_even_with_no_project_open(monkeypatch) -> None:
    # Oct 12 2026: after a restart Ducky had no project open, so the keeper saw no team at all.
    import backend.agent.coding_agents.plans as plans
    from frontend.settings import PanelSettings

    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: type("S", (), {"uefn_project_root": ""})()))
    monkeypatch.setattr("frontend.ui_web.recent_projects.load_recent_projects", lambda: ["C:/Repo", "c:/repo/", "C:/Other"])
    assert keeper._project_roots(None) == ["C:/Repo", "C:/Other"]
    by_root = {"C:/Repo": [{**PLAN, "chat_id": "lead"}], "C:/Other": []}
    monkeypatch.setattr(plans, "list_plans", lambda project_root=None: by_root.get(project_root, []))
    leaders_read: list[str] = []
    monkeypatch.setattr(keeper, "_team_leaders", lambda root: leaders_read.append(root) or {"lead"})
    kept = keeper.kept_plans()
    assert [(p["chat_id"], p["project_root"]) for p in kept] == [("lead", "C:/Repo")]
    assert leaders_read == ["C:/Repo"]  # a project with no live plan isn't read
