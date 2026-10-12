"""Team keeper: wakes a team's coordinator when its plan has open work and nobody is working.

A coordinator agent only runs when a message wakes it. When it ended a turn with no
reply on the way, or the AI account ran out of credits, the whole team stopped until a
person noticed and nudged it. The keeper is that nudge, inside Ducky.

A plan is kept going while it has started, is not paused or finished, still has open
steps, and its chat leads a group. Pausing the plan stops the keeper for it. Three wakes
in a row that move nothing (no member works, no step changes status or owner) park it
until something does: a plan waiting on the user's own step was woken every hour, and
each wake re-read the coordinator's whole thread.

A team can also go in circles while busy: on Oct 11 2026 six agents worked for an hour,
sent 292 messages, and finished no step, all waiting on one export the plugin's own gate
would never start. A team that stays busy for ``_STALL_S`` without finishing a step gets
one circle notice for its coordinator, and the person is alerted.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

_TICK_S = 60.0
_IDLE_S = 120.0  # nobody running this long before a wake
_MAX_WAIT_S = 3600.0  # wakes that start no work back off up to this
_PARK_AFTER = 3  # wakes in a row that moved nothing: wait for a change instead
_PARKED_TABLE = "workspace_state"
# Steps are sized 15-30 minutes and builders work in parallel: a team busy this long
# with no finished step is going in circles (45 minutes was too long for the owner).
_STALL_S = 20 * 60.0

WAKE_TEXT = (
    "[Ducky keeper] Your team has had no agent running for {minutes} minutes and the plan "
    "still has {open_steps} open steps. Re-read the charter and the plan, check each "
    "in-progress step and its agent (ducky_agent_list, ducky_agent_transcript), and dispatch "
    "the work that can move now. If you are blocked on a decision only the user can make, "
    "say exactly which one and end your turn."
)

STALL_TEXT = (
    "[Ducky keeper] Your team has been working for {minutes} minutes and no plan step has "
    "finished ({done} of {total} done). Busy without finishing is a circle. In this turn: "
    "name in one sentence the one thing the open steps are waiting on; give it to one owner, "
    "or ask the person with ducky_ask_user if only they can decide it; tell everyone else to "
    "finish their own steps without waiting for it; and give a member that keeps reporting "
    "the same blocker a fresh start (ducky_recycle_member) with a short brief. "
    "No status rounds, no relays, no acknowledgements."
)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
# coordinator chat id -> {"quiet_since": t, "wakes": n, "next_wake": t, "moves": plan fingerprint}
_teams: dict[str, dict[str, Any]] = {}


def _open_steps(plan: dict[str, Any]) -> int:
    prog = plan.get("progress") or {}
    return int(prog.get("pending") or 0) + int(prog.get("in_progress") or 0)


def _started(plan: dict[str, Any]) -> bool:
    prog = plan.get("progress") or {}
    return int(prog.get("completed") or 0) + int(prog.get("in_progress") or 0) > 0


def _done(plan: dict[str, Any]) -> int:
    return int((plan.get("progress") or {}).get("completed") or 0)


def _total(plan: dict[str, Any]) -> int:
    prog = plan.get("progress") or {}
    return sum(int(prog.get(k) or 0) for k in ("pending", "in_progress", "completed", "cancelled"))


def _tell_person(cid: str, minutes: int) -> None:
    try:
        from frontend.notifications import alert
        from frontend.ui_web.project_chats import load_conversation

        conv = load_conversation(cid)
        name = str(getattr(conv, "title", "") or "").strip() or "Your team"
        alert(name, f"No plan step finished in {minutes} minutes of work.", level="info",
              kind="chat", target_id=cid)
    except Exception:
        pass


def _moves(plan: dict[str, Any]) -> str:
    """What counts as the plan moving: the plan's status and each step's status and owner."""
    parts = [str(plan.get("status") or "")]
    stack = list(plan.get("nodes") or [])
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            parts.append(f"{node.get('id')}:{node.get('status')}:{node.get('assignee') or ''}")
            stack.extend(node.get("children") or [])
    return "|".join(sorted(parts))


def _team_leaders(project_root: str | None) -> set[str]:
    from frontend.ui_web.group_orchestrator import is_group_conversation
    from frontend.ui_web.project_chats import list_all_conversation_metadata

    leaders: set[str] = set()
    for conv in list_all_conversation_metadata(project_root):
        if is_group_conversation(conv):
            lid = (getattr(conv, "leader_conv_id", None) or "").strip()
            if lid:
                leaders.add(lid)
    return leaders


def _project_roots(project_root: str | None) -> list[str]:
    """The open project and the recent ones: a team keeps working in its own project while the
    person has another open, or none (Oct 12 2026: after a restart with no project open, the
    keeper saw no team at all)."""
    if project_root is not None:
        return [project_root]
    from frontend.settings import PanelSettings
    from frontend.ui_web.recent_projects import load_recent_projects

    roots: list[str] = []
    seen: set[str] = set()
    for root in [PanelSettings.load().uefn_project_root or "", *load_recent_projects()]:
        key = str(root or "").replace("\\", "/").rstrip("/").lower()
        if key and key not in seen:
            seen.add(key)
            roots.append(str(root))
    return roots


_DORMANT_S = 2 * 3600.0  # a team plan unchanged this long is left alone until it changes again


def _dormant(plan: dict[str, Any], now: float) -> bool:
    """An old team's plan nobody touched for hours: the keeper must not bring that team back.
    Oct 12 2026: scanning recent projects woke six chats of three earlier teams at once."""
    updated = float(plan.get("updated_at") or 0.0)
    return updated > 0 and now - updated > _DORMANT_S


def kept_plans(project_root: str | None = None) -> list[dict[str, Any]]:
    """Team plans the keeper looks after right now, in every project the person works in."""
    from backend.agent.coding_agents.plans import list_plans

    out: list[dict[str, Any]] = []
    now = time.time()
    for root in _project_roots(project_root):
        live = [plan for plan in list_plans(root)
                if str(plan.get("status") or "open") not in ("paused", "finished", "completed", "archived")
                and _started(plan) and _open_steps(plan) and not _dormant(plan, now)]
        if not live:
            continue  # the team lookup reads every chat of the project: only when needed
        leaders = _team_leaders(root)
        for plan in live:
            if str(plan.get("chat_id") or "") in leaders:
                plan.setdefault("project_root", root)
                out.append(plan)
    return out


def _wake(chat_id: str, text: str) -> None:
    from frontend.ui_web.agent_modes import run_message
    from frontend.ui_web.project_chats import load_conversation

    conv = load_conversation(chat_id)
    model = str(getattr(conv, "model", "") or "") if conv is not None else ""
    # A follow-up in the coordinator's own chat: it keeps that chat's approvals.
    run_message(chat_id, text, "agent", model, queue_if_busy=True)


def _team_context(plan: dict[str, Any]) -> tuple[set[str], str]:
    from backend.agent.coding_agents.plans import _chat_and_group_ids
    from backend.agent.coding_agents.team_plan_events import assigned_nodes
    from frontend.ui_web.project_chats import list_all_conversation_metadata

    nodes = list(assigned_nodes(plan.get("nodes")))
    owners = {owner for _, owner in nodes if owner}
    members = {}
    for conv in list_all_conversation_metadata(plan.get("project_root")) if owners else []:
        cid = str(getattr(conv, "id", ""))
        if not getattr(conv, "is_group", False) and owners.intersection(_chat_and_group_ids(cid, plan.get("project_root"))):
            members[cid] = getattr(conv, "ducky_name", "") or getattr(conv, "title", "") or cid
    open_names = [f"{n['content']} ({n['id']})" for n, _ in nodes
                  if n.get("status") not in {"completed", "cancelled"} and not n.get("children")]
    from backend.agent.a2a_broker import unanswered_reports

    reports = [r["body"] for r in plan.get("team_reports", [])]
    reports += [r["body"] for r in unanswered_reports(str(plan.get("chat_id") or ""))]
    detail = "\nOpen steps: " + ("; ".join(open_names) or "see plan")
    detail += "\nIdle members: " + ("; ".join(f"{name} ({cid})" for cid, name in members.items()) or "none listed")
    if reports:
        detail += "\nReports awaiting next dispatch:\n" + "\n".join(reports)
    return set(members) | owners, detail


def tick(
    *,
    now: float | None = None,
    plans: list[dict[str, Any]] | None = None,
    running: list[str] | None = None,
    wake: Callable[[str, str], None] | None = None,
) -> list[str]:
    """One check. Returns the coordinator chats it woke (arguments are for tests)."""
    from backend.agent.a2a_broker import automatic_work_blocked

    now = time.time() if now is None else now
    if plans is None:
        plans = kept_plans()
    if running is None:
        from frontend.ui_web.agent_modes import list_running_agents

        running = list(list_running_agents())
    wake = wake or _wake
    busy = set(running)
    woke: list[str] = []
    with _lock:
        live = {str(p.get("chat_id") or "") for p in plans}
        for gone in [cid for cid in _teams if cid not in live]:
            _teams.pop(gone, None)
        for plan in plans:
            cid = str(plan.get("chat_id") or "")
            st = _teams.get(cid)
            if st is None:
                st = _teams[cid] = {"quiet_since": now, "wakes": 0.0, "next_wake": 0.0}
                parked = _load_parked(cid)
                if parked is not None:
                    # Parked before a restart: three more wakes per app start added up.
                    st["moves"], st["wakes"] = parked, float(_PARK_AFTER)
            done = _done(plan)
            if "done" not in st or done > st["done"]:
                st["done"], st["progress_at"], st["next_stall"] = done, now, 0.0
            member_ids, details = _team_context(plan)
            team_busy = busy.intersection(member_ids | {cid}) if member_ids else busy
            if team_busy:
                st["quiet_since"] = now
                if team_busy - {cid}:
                    _unpark(cid, st)  # the team is working again: drop the backoff
                if now - st["progress_at"] >= _STALL_S and now >= st["next_stall"]:
                    minutes = int((now - st["progress_at"]) // 60)
                    try:
                        wake(cid, STALL_TEXT.format(minutes=minutes, done=done, total=_total(plan)) + details)
                    except Exception:
                        continue
                    _tell_person(cid, minutes)
                    st["next_stall"] = now + _STALL_S
                    woke.append(cid)
                continue
            moves = _moves(plan)
            if st.get("moves") != moves:
                st["moves"] = moves
                _unpark(cid, st)  # a step moved: the next quiet spell wakes it again
            if st["wakes"] >= _PARK_AFTER:
                continue
            if automatic_work_blocked(cid) or now - st["quiet_since"] < _IDLE_S or now < st["next_wake"]:
                continue
            minutes = int((now - st["quiet_since"]) // 60)
            text = WAKE_TEXT.format(minutes=minutes, open_steps=_open_steps(plan)) + details
            try:
                wake(cid, text)
            except Exception:
                continue
            st["wakes"] += 1
            if st["wakes"] >= _PARK_AFTER:
                _save_parked(cid, moves)
            # A wake that starts no work waits longer each time: 2, 4, 8, 16, 32, 60 minutes.
            st["next_wake"] = now + min(_IDLE_S * (2 ** (st["wakes"] - 1)), _MAX_WAIT_S)
            st["quiet_since"] = now
            woke.append(cid)
        woke.extend(_continue_members(plans, busy, now, wake))
    return woke


CONTINUE_TEXT = (
    "[Ducky keeper] You have open plan steps:\n{steps}\nContinue with the first one you can do "
    "now. If every one is waiting on someone else's work, end your turn with one line saying "
    "what it waits for. Don't ask your lead what to do next."
)
_MEMBER_IDLE_S = 90.0  # a builder idle this long with open steps gets its next turn
_MEMBER_TRIES = 2  # wakes that move nothing in the plan: wait for the plan to move
_members: dict[str, dict[str, Any]] = {}


def _open_leaves_by_member(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Open steps per owner, leaving out steps (and sections) whose ``after`` steps are unfinished:
    a builder told to "continue" with a step that runs last checked it and said "waiting" every
    few minutes."""
    from backend.agent.coding_agents.plans import waiting_on

    out: dict[str, list[dict[str, Any]]] = {}
    stack = [(node, False) for node in plan.get("nodes") or []]
    while stack:
        node, held = stack.pop(0)
        if not isinstance(node, dict):
            continue
        held = held or bool(waiting_on(plan, node))
        kids = node.get("children") or []
        stack[:0] = [(kid, held) for kid in kids]
        owner = str(node.get("assignee") or "").strip()
        if owner and not kids and not held and node.get("status") in ("pending", "in_progress"):
            out.setdefault(owner, []).append(node)
    return out


def _continue_members(plans: list[dict[str, Any]], busy: set[str], now: float,
                      wake: Callable[[str, str], None]) -> list[str]:
    """A builder that stops after each report waited for its lead to say "resume": one lead
    sent 91 messages in 50 minutes, most of them that. Ducky starts the builder's next turn
    itself, twice at most until the plan moves (a blocked builder is not woken forever).
    Must hold ``_lock``."""
    from backend.agent.a2a_broker import automatic_work_blocked

    woke: list[str] = []
    for plan in plans:
        lead = str(plan.get("chat_id") or "")
        moves = _moves(plan)
        for member, steps in _open_leaves_by_member(plan).items():
            if member == lead:
                continue
            st = _members.setdefault(member, {"idle_since": now, "tries": 0, "next": 0.0, "moves": moves})
            if st["moves"] != moves:
                st.update(moves=moves, tries=0, next=0.0)  # the plan moved: try again
            if member in busy:
                st["idle_since"] = now
                continue
            if (now - st["idle_since"] < _MEMBER_IDLE_S or now < st["next"]
                    or st["tries"] >= _MEMBER_TRIES or automatic_work_blocked(member)):
                continue
            listing = "\n".join(f"- `{n.get('id')}` {n.get('content')} ({n.get('status')})" for n in steps)
            try:
                wake(member, CONTINUE_TEXT.format(steps=listing))
            except Exception:
                continue
            st["tries"] += 1
            st["idle_since"] = now
            st["next"] = now + _MEMBER_IDLE_S * 2
            woke.append(member)
    return woke


def _unpark(cid: str, st: dict[str, Any]) -> None:
    if st["wakes"] >= _PARK_AFTER:
        _save_parked(cid, None)
    st["wakes"] = 0.0
    st["next_wake"] = 0.0


def _parked_key(cid: str) -> str:
    return f"team_keeper_parked:{cid}"


def _load_parked(cid: str) -> str | None:
    """The plan fingerprint this coordinator was parked at, kept across restarts."""
    try:
        from backend.store.switch import use_db

        if not use_db(_PARKED_TABLE):
            return None
        from backend.store.repos import kv

        doc = kv.get_doc(_PARKED_TABLE, _parked_key(cid))
        return str(doc["moves"]) if isinstance(doc, dict) and "moves" in doc else None
    except Exception:
        return None


def _save_parked(cid: str, moves: str | None) -> None:
    try:
        from backend.store.switch import use_db

        if not use_db(_PARKED_TABLE):
            return
        from backend.store.repos import kv

        if moves is None:
            kv.delete_doc(_PARKED_TABLE, _parked_key(cid))
        else:
            kv.set_doc(_PARKED_TABLE, _parked_key(cid), {"moves": moves, "at": time.time()})
    except Exception:
        pass  # parking is a token saver; never let it stop the keeper


def _loop() -> None:
    while not _stop.wait(_TICK_S):
        try:
            tick()
        except Exception:
            pass


def start_team_keeper() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="team-keeper")
        _thread.start()


def stop_team_keeper() -> None:
    _stop.set()


def reset_for_tests() -> None:
    with _lock:
        _teams.clear()
        _members.clear()
