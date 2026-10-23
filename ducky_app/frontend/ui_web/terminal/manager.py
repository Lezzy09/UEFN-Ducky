"""Thread-safe terminal session manager with agent command approval."""

from __future__ import annotations

import functools
import os
import threading
import time
import uuid
from typing import Any, Callable

from frontend.settings import PanelSettings
from frontend.ui_web.terminal.bridge import TerminalBridge
from frontend.ui_web.terminal.session import (
    _OUTPUT_RING_CHARS,
    PendingCommand,
    ProcessSnapshot,
    TerminalSession,
    _process_snapshot,
    agent_command_output,
)
from frontend.ui_web.terminal.shells import shell_label

_APPROVAL_TIMEOUT_S = 120.0
# Terminals one chat may keep open. Each holds a shell, a conhost and a socket bridge,
# and an agent that opens one per turn in different folders piled them up all day.
_MAX_CHAT_SHELLS = 6
# An agent's terminal with no output, no typing and nothing running for this long, while its
# agent is not working, is closed. Agents never closed theirs: a team left one shell (a
# shell, a conhost and a socket bridge) per member open until Ducky quit (Oct 15 2026).
# Oct 22 2026: ten minutes still left a header full of finished duckies' shells; a ducky's
# terminal now closes about a minute after it finishes.
_AGENT_IDLE_CLOSE_S = 60.0
_REAP_EVERY_S = 15.0
_manager: "TerminalManager | None" = None
_manager_lock = threading.Lock()


def _default_cwd() -> str:
    root = PanelSettings.load().uefn_project_root.strip()
    return root or "."


def _chat_title(conv_id: str) -> str:
    """The ducky (chat) a terminal belongs to, as the header list names it."""
    if not conv_id:
        return ""
    try:
        from frontend.ui_web.project_chats import conversation_title

        return conversation_title(conv_id)
    except Exception:
        return ""


class TerminalManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionEntry] = {}
        self._pending: dict[str, PendingCommand] = {}
        # Answered before the agent's thread got to wait_for_approval (a quick click):
        # the waiter still finds the answer. The newest few only; a waiter pops its own.
        self._decided: dict[str, PendingCommand] = {}
        self._reaper: threading.Thread | None = None
        self._reaper_stop = threading.Event()
        # Terminals a running workflow still needs: never closed as idle until it lets go.
        self._held: set[str] = set()
        self._push: Callable[[dict[str, Any]], None] | None = None

    def set_push(self, push: Callable[[dict[str, Any]], None] | None) -> None:
        self._push = push

    def _emit(self, event: dict[str, Any]) -> None:
        push = self._push
        if push:
            try:
                push(event)
            except Exception:
                pass

    def spawn(
        self,
        shell: str = "bash",
        cwd: str | None = None,
        title: str = "",
        *,
        push_open: bool = False,
        hidden: bool = False,
        conv_id: str = "",
        command: list[str] | None = None,
        env_extra: dict[str, str] | None = None,
        activate: bool = True,
        reuse_idle: bool = False,
    ) -> dict[str, Any]:
        """``reuse_idle``: hand back this chat's idle live terminal with the same shell
        and folder instead of a new one. Agents that open a terminal every turn used
        to stack a shell, a conhost and a socket bridge per call."""
        shell_norm = shell_label(shell)
        workdir = (cwd or _default_cwd()).strip() or "."
        if not os.path.isdir(workdir):
            workdir = os.getcwd()
        argv = [str(a) for a in command] if command else None
        extra = {str(k): str(v) for k, v in (env_extra or {}).items() if k} or None
        reuse_key = (conv_id, shell_norm, workdir) if conv_id and not argv and not hidden and not extra else None
        if reuse_idle and reuse_key is not None:
            idle = self._idle_session(reuse_key)
            if idle is not None:
                if push_open:
                    self._emit_open(idle, conv_id, activate)
                return {
                    "ok": True,
                    **idle.to_dict(),
                    "tab_id": f"terminal:{idle.id}",
                    "shell_fallback": False,
                    "reused": True,
                }
        closed = self._make_room(conv_id) if conv_id else []
        entry: _SessionEntry | None = None
        with self._lock:
            session = TerminalSession(
                shell=shell_norm,
                cwd=workdir,
                title=title,
                hidden=hidden,
                spawn_argv=argv,
                env_extra=extra,
            )  # type: ignore[arg-type]
            bridge = TerminalBridge(
                on_input=lambda data, s=session: self._user_write(s.id, data),
                on_resize=lambda c, r, s=session: s.resize(c, r),
                # A tab shown again gets its whole kept history back, not just the last screen.
                get_replay=lambda s=session: s.read_output_tail(_OUTPUT_RING_CHARS),
                get_status=lambda s=session: self._session_status(s),
            )
            bridge.start()
            session.port = bridge.port
            session.ws_url = bridge.ws_url

            def on_output(text: str, b=bridge) -> None:
                b.push_output(text)

            def on_exit(code: int, b=bridge) -> None:
                b.push_exit(code)

            session._on_output = on_output  # type: ignore[attr-defined]
            session._on_exit = on_exit  # type: ignore[attr-defined]
            shell_fallback = False
            try:
                session.spawn()
            except Exception as exc:
                if argv:
                    bridge.stop()
                    return {"ok": False, "error": str(exc)}
                if shell_norm == "bash":
                    session.shell = "powershell"
                    shell_norm = "powershell"
                    shell_fallback = True
                    try:
                        session.spawn()
                    except Exception as exc2:
                        bridge.stop()
                        return {"ok": False, "error": str(exc2), "hint": f"bash failed ({exc}); powershell also failed"}
                else:
                    bridge.stop()
                    return {"ok": False, "error": str(exc)}
            session.owner = _chat_title(conv_id)
            entry = _SessionEntry(session=session, bridge=bridge, reuse_key=reuse_key, chat=conv_id)
            self._sessions[session.id] = entry

        result = {
            "ok": True,
            **session.to_dict(),
            "tab_id": f"terminal:{session.id}",
            "shell_fallback": shell_fallback,
        }
        if closed:
            result["closed"] = closed
        if push_open and not session.hidden:
            self._emit_open(session, conv_id, activate)
        if conv_id:
            self._ensure_reaper()
        return result

    def _ensure_reaper(self) -> None:
        with self._lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            self._reaper = threading.Thread(target=self._reap_loop, daemon=True, name="terminal-reaper")
            self._reaper.start()

    def _reap_loop(self) -> None:
        while not self._reaper_stop.wait(_REAP_EVERY_S):
            try:
                self.close_idle_agent_terminals()
            except Exception:
                pass

    def hold(self, session_id: str) -> Callable[[], None]:
        """Keep this terminal from the idle reaper while a workflow run goes on; the run
        calls the returned function when it ends."""
        with self._lock:
            self._held.add(session_id)

        def release() -> None:
            with self._lock:
                self._held.discard(session_id)

        return release

    def close_idle_agent_terminals(
        self,
        *,
        now: float | None = None,
        running: set[str] | None = None,
    ) -> list[str]:
        """Close agents' terminals they are done with: the agent is not working (or its chat
        is gone) and the terminal has been quiet for ``_AGENT_IDLE_CLOSE_S``. A terminal running
        anything, waiting on an Allow card, held by a running workflow, or where the agent
        started a background command (a dev server) is kept, and a person's own terminals
        (no chat) are never closed."""
        now = time.time() if now is None else now
        if running is None:
            from frontend.ui_web.agent_modes import list_running_agents

            running = set(list_running_agents())
        with self._lock:
            agents = [(e.session, e.chat) for e in self._sessions.values() if e.chat]
            asked = {p.session_id for p in self._pending.values()}
            held = set(self._held)
        snapshot = functools.cache(_process_snapshot)
        closed: list[str] = []
        for session, chat in agents:
            if (chat in running or session.id in asked or session.id in held
                    or getattr(session, "ran_background", False)
                    or session.has_running_command(snapshot)):
                continue
            if now - float(getattr(session, "last_activity", now)) >= _AGENT_IDLE_CLOSE_S:
                if self.kill(session.id).get("ok"):
                    closed.append(session.id)
        return closed

    def _idle_session(self, reuse_key: tuple[str, str, str]) -> TerminalSession | None:
        with self._lock:
            candidates = [e.session for e in self._sessions.values() if e.reuse_key == reuse_key]
        for session in candidates:
            if session.is_alive() and not session.has_running_command():
                return session
        return None

    def _make_room(self, conv_id: str) -> list[str]:
        """Close the chat's oldest idle terminals so a new one keeps it within the cap.

        A terminal running a command or waiting on an Allow pop-up is never closed, and
        when every one is busy the new terminal opens anyway. A person's own terminals
        belong to no chat and are never counted."""
        with self._lock:
            mine = [e.session for e in self._sessions.values() if e.chat == conv_id]
            asked = {p.session_id for p in self._pending.values()}
        excess = len(mine) - _MAX_CHAT_SHELLS + 1
        if excess <= 0:
            return []
        snapshot = functools.cache(_process_snapshot)
        idle = [s for s in mine if s.id not in asked and not s.has_running_command(snapshot)]
        # Terminals whose shell already ended go first, then the oldest (open order).
        idle.sort(key=lambda s: s.is_alive())
        closed = [s.id for s in idle[:excess]]
        for session_id in closed:
            self.kill(session_id)
        return closed

    def _emit_open(self, session: TerminalSession, conv_id: str, activate: bool) -> None:
        self._emit(
            {
                "type": "terminal_open",
                "session_id": session.id,
                "shell": session.shell,
                "title": session.title,
                "cwd": session.cwd,
                "ws_url": session.ws_url,
                "conv_id": conv_id,
                "owner": session.owner,
                "activate": bool(activate),
            }
        )

    def busy_state(self, session_id: str, snapshot: ProcessSnapshot | None = None) -> dict[str, Any]:
        """Whether a command (agent or user-typed) is running in the session."""
        session = self.get_session(session_id)
        if not session:
            return {"ok": False, "error": "session not found"}
        return {
            "ok": True,
            "session_id": session_id,
            "busy": session.is_busy(),
            "running": session.has_running_command(snapshot),
        }

    def busy_state_many(self, session_ids: list[str]) -> dict[str, Any]:
        """busy_state for several sessions at once.

        Telling whether a user-typed command runs walks every process on the PC (~10 ms);
        the header polls all its terminals every few seconds, so they share one walk.
        """
        snapshot = functools.cache(_process_snapshot)
        ids = dict.fromkeys(str(sid).strip() for sid in session_ids or [] if str(sid).strip())
        return {"ok": True, "states": {sid: self.busy_state(sid, snapshot) for sid in ids}}

    def kill(self, session_id: str, *, push_close: bool = True) -> dict[str, Any]:
        entry = self._pop_session(session_id)
        if entry is None:
            return {"ok": False, "error": "session not found"}
        if push_close:
            self._emit({"type": "terminal_close", "session_id": session_id})
        return {"ok": True, "session_id": session_id}

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.session.to_dict() for e in self._sessions.values() if not e.session.hidden]

    def get_session(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            return entry.session if entry else None

    def _session_status(self, session: TerminalSession) -> dict[str, Any]:
        alive = session.is_alive()
        exit_code = session._exit_code
        return {
            "alive": alive,
            "exit_code": exit_code,
        }

    def _user_write(self, session_id: str, data: str) -> None:
        session = self.get_session(session_id)
        if not session:
            return
        if not session.is_alive():
            with self._lock:
                entry = self._sessions.get(session_id)
            if entry:
                entry.bridge.push_status({"alive": False, "exit_code": session._exit_code})
            return
        try:
            session.write(data)
        except Exception:
            pass

    def write(self, session_id: str, data: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            return {"ok": False, "error": "session not found"}
        try:
            session.write(data)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def resize(self, session_id: str, cols: int, rows: int) -> dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            return {"ok": False, "error": "session not found"}
        session.resize(cols, rows)
        return {"ok": True}

    def request_command(
        self,
        session_id: str,
        command: str,
        source: str = "",
        conv_id: str = "",
        *,
        background: bool = False,
        push_pending: bool = True,
        runner_waits: bool = False,
        timeout_s: float = 300.0,
    ) -> dict[str, Any]:
        cmd = (command or "").strip()
        if not cmd:
            return {"ok": False, "error": "command must not be empty"}
        session = self.get_session(session_id)
        if not session:
            return {"ok": False, "error": "session not found"}
        if session.is_busy() and not background:
            return {
                "ok": False,
                "error": "session busy",
                "hint": "Wait for the current command or open another terminal with ducky_terminal_open.",
            }
        request_id = uuid.uuid4().hex[:12]
        cwd = str(getattr(session, "cwd", "") or "")
        offers = _card_offers(cmd, cwd) if push_pending else {}
        lead, asked_by = _lead_of(conv_id) if push_pending else ("", "")
        pending = PendingCommand(
            request_id=request_id,
            session_id=session_id,
            command=cmd,
            source=source or "agent",
            conv_id=conv_id,
            background=background,
            runner_waits=runner_waits and not background,
            timeout_s=float(timeout_s),
            asked=bool(push_pending),
            rule_label=str(offers.get("rule_label") or ""),
            shell=str(getattr(session, "shell", "") or ""),
            cwd=cwd,
            lead_conv_id=lead,
            asked_by=asked_by,
        )
        with self._lock:
            self._pending[request_id] = pending
        if push_pending:
            # A card in the chat that asked (conv_id) and in its lead's chat; with no chat, an
            # entry in the header's background activity list.
            self._emit({"type": "terminal_command_pending", **_pending_dict(pending, source or "ducky_terminal_run")})
            _alert_command(lead or conv_id, cmd, asked_by if lead else "")
        return {"ok": True, "request_id": request_id, "status": "pending_approval"}

    def list_pending(self) -> list[dict[str, Any]]:
        """Unanswered command cards, oldest first (a window that reloads shows them again)."""
        with self._lock:
            rows = [p for p in self._pending.values() if p.asked and not p.decided.is_set()]
        rows.sort(key=lambda p: p.created_at)
        return [_pending_dict(p, p.source) for p in rows]

    def approve_command(self, request_id: str, scope: str = "once", answered_in: str = "") -> dict[str, Any]:
        """scope: once, always (this command, in its chat) or all (everything, in its chat).
        answered_in: the chat whose card was used; the lead's card saves the choice on the lead,
        which covers every member its plan starts."""
        pending = self._take_pending(request_id)
        if pending is None:
            return {"ok": False, "error": "request not found or already decided"}
        saved = _remember_choice(pending, scope, answered_in) if scope in ("always", "all") else "once"
        session = self.get_session(pending.session_id)
        if not session:
            pending.approved = False
            pending.rejection_reason = "session not found"
            pending.decided.set()
            return {"ok": False, "error": "session not found"}
        pending.approved = True
        pending.decided.set()
        if pending.runner_waits:
            return {"ok": True, "request_id": request_id, "saved": saved, "run": {"ok": True, "status": "approved"}}
        if pending.background:
            result = session.run_command(pending.command, background=True)
        else:
            # Run after signaling approval so agent waiters unblock; avoid blocking UI on completion.
            threading.Thread(
                target=session.run_command,
                args=(pending.command,),
                kwargs={"background": False, "timeout_s": pending.timeout_s},
                daemon=True,
                name=f"terminal-run-{request_id}",
            ).start()
            result = {"ok": True, "status": "running"}
        return {"ok": True, "request_id": request_id, "saved": saved, "run": result}

    def reject_command(self, request_id: str, reason: str = "rejected by user") -> dict[str, Any]:
        pending = self._take_pending(request_id)
        if pending is None:
            return {"ok": False, "error": "request not found or already decided"}
        pending.approved = False
        pending.rejection_reason = reason
        pending.decided.set()
        return {"ok": True, "request_id": request_id, "approved": False, "reason": reason}

    def wait_for_approval(self, request_id: str, timeout_s: float = _APPROVAL_TIMEOUT_S) -> dict[str, Any]:
        with self._lock:
            pending = self._pending.get(request_id) or self._decided.pop(request_id, None)
        if pending is None:
            return {"ok": False, "error": "request not found"}
        if not pending.decided.wait(timeout=max(1.0, float(timeout_s))):
            self.reject_command(request_id, reason="command not approved (timed out)")
            return {"ok": False, "error": "command not approved (timed out)"}
        if not pending.approved:
            return {"ok": False, "error": pending.rejection_reason or "command rejected by user"}
        with self._lock:
            self._pending.pop(request_id, None)
        return {"ok": True, "approved": True}

    def run_agent_command(
        self,
        session_id: str,
        command: str,
        *,
        source: str = "",
        conv_id: str = "",
        background: bool = False,
        wait: bool = True,
        approval_timeout_s: float = _APPROVAL_TIMEOUT_S,
        command_timeout_s: float = 300.0,
        auto_approve: bool = False,
    ) -> dict[str, Any]:
        """auto_approve: the chat said "Allow everything", so no Allow/Deny card. A command
        the chat said "Always allow" for runs without one too.

        wait (not background): the command runs on this thread and the result is its
        exit code; a command that fails is ok=False."""
        runs_here = wait and not background
        if not auto_approve and conv_id:
            known = self.get_session(session_id)
            auto_approve = _chat_always_allows(conv_id, command, str(getattr(known, "cwd", "") or ""))
        req = self.request_command(
            session_id,
            command,
            source=source,
            conv_id=conv_id,
            background=background,
            push_pending=not auto_approve,
            runner_waits=runs_here,
            timeout_s=command_timeout_s,
        )
        if not req.get("ok"):
            return req
        request_id = str(req["request_id"])
        if auto_approve:
            approval = self.approve_command(request_id)
        else:
            approval = self.wait_for_approval(request_id, timeout_s=approval_timeout_s)
        if not approval.get("ok"):
            return approval
        session = self.get_session(session_id)
        if session is None:
            return {"ok": False, "error": "session not found"}
        if not runs_here:
            return {
                "ok": True,
                "request_id": request_id,
                "session_id": session_id,
                "status": "running",
            }
        ran = session.run_command(command.strip(), background=False, timeout_s=command_timeout_s)
        # A command that printed nothing reports nothing. Falling back to the raw screen gave
        # the agent escape codes and its own echoed command instead (a silent failed push).
        tail = ran["output_tail"] if "output_tail" in ran else agent_command_output(session.read_output_tail(max_chars=_OUTPUT_RING_CHARS))
        out: dict[str, Any] = {
            "ok": bool(ran.get("ok")),
            "request_id": request_id,
            "session_id": session_id,
            "output_tail": str(tail),
        }
        if not out["ok"]:
            return {**out, "error": str(ran.get("error") or "command failed"), **({"hint": ran["hint"]} if ran.get("hint") else {})}
        code = ran.get("exit_code")
        out["exit_code"] = code
        if code not in (None, 0):
            return {**out, "ok": False, "error": f"Command failed (exit code {code})."}
        return out

    def read_output(self, session_id: str, max_chars: int = 8000) -> dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            return {"ok": False, "error": "session not found"}
        return {
            "ok": True,
            "session_id": session_id,
            "output": session.read_output_tail(max_chars=max_chars),
            "busy": session.is_busy(),
            "alive": session.is_alive(),
        }

    def shutdown_all(self) -> None:
        self._reaper_stop.set()
        with self._lock:
            ids = list(self._sessions.keys())
            pending_ids = list(self._pending.keys())
        for rid in pending_ids:
            self.reject_command(rid, reason="panel shutting down")
        for sid in ids:
            self.kill(sid, push_close=False)

    def _take_pending(self, request_id: str) -> PendingCommand | None:
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is not None and pending.runner_waits:
                self._decided[request_id] = pending
                for old in list(self._decided)[:-32]:
                    self._decided.pop(old, None)
        if pending is not None and pending.asked:
            # Every window (and a page replaying the backlog after a reload) drops
            # its Allow pop-up: the question was answered here, or timed out.
            self._emit({
                "type": "terminal_command_decided",
                "request_id": pending.request_id,
                "conv_id": pending.conv_id,
            })
        return pending

    def _pop_session(self, session_id: str) -> "_SessionEntry | None":
        with self._lock:
            entry = self._sessions.pop(session_id, None)
        if entry is None:
            return None
        with self._lock:
            pending_ids = [rid for rid, pending in self._pending.items() if pending.session_id == session_id]
        for rid in pending_ids:
            self.reject_command(rid, reason="terminal closed")
        entry.session.kill()
        entry.bridge.stop()
        return entry


def _card_offers(command: str, cwd: str) -> dict[str, Any]:
    try:
        from backend.tools.panel.terminal_approval import describe_command

        return describe_command(command, cwd)
    except Exception:
        return {"rule_label": ""}


def _chat_always_allows(conv_id: str, command: str, cwd: str) -> bool:
    try:
        from backend.tools.panel.terminal_approval import allows

        return allows(conv_id, command, cwd)
    except Exception:
        return False


def _remember_choice(pending: PendingCommand, scope: str, answered_in: str = "") -> str:
    chat = pending.conv_id
    if answered_in and answered_in == pending.lead_conv_id:
        chat = answered_in  # "in this chat" on the lead's card means the lead's chat
    if not chat:
        return "once"
    try:
        from backend.tools.panel.terminal_approval import remember

        return remember(chat, pending.command, scope, cwd=pending.cwd)
    except Exception:
        return "once"


def _lead_of(conv_id: str) -> tuple[str, str]:
    """The lead chat a member's card also shows in, and the member's name ('' when none)."""
    if not conv_id:
        return "", ""
    try:
        from backend.tools.panel.permission_prompt import starter_root
        from frontend.ui_web.project_chats import load_conversation

        lead = starter_root(conv_id)
        if not lead or lead == conv_id:
            return "", ""
        conv = load_conversation(conv_id)
        name = str(getattr(conv, "ducky_name", "") or getattr(conv, "title", "") or "").strip() if conv else ""
        return lead, name or "Team member"
    except Exception:
        return "", ""


def _alert_command(conv_id: str, command: str, asked_by: str = "") -> None:
    """A command waits for the person's OK: alert (frontend.notifications). The command
    shows in the Windows notification only. Off-thread: naming the chat reads it from disk.
    A member's command alerts its lead's chat (``conv_id``), naming the member (``asked_by``)."""

    def send() -> None:
        try:
            from frontend.notifications import alert
            from frontend.ui_web.project_chats import load_conversation

            conv = load_conversation(conv_id) if conv_id else None
            title = str(getattr(conv, "title", "") or "").strip() or "UEFN Ducky"
            status = f"{asked_by} wants to run a command." if asked_by else "Wants to run a command."
            alert(title, status, level="ask", kind="chat" if conv else "",
                  target_id=conv_id if conv else "", detail=command)
        except Exception:
            pass

    threading.Thread(target=send, daemon=True, name="command-alert").start()


def _pending_dict(pending: PendingCommand, source: str) -> dict[str, Any]:
    return {
        "request_id": pending.request_id,
        "session_id": pending.session_id,
        "command": pending.command,
        "shell": pending.shell,
        "cwd": pending.cwd,
        "conv_id": pending.conv_id,
        "source": source,
        "rule_label": pending.rule_label,
        "created_at": pending.created_at,
        "lead_conv_id": pending.lead_conv_id,
        "asked_by": pending.asked_by,
    }


class _SessionEntry:
    __slots__ = ("session", "bridge", "reuse_key", "chat")

    def __init__(
        self,
        *,
        session: TerminalSession,
        bridge: TerminalBridge,
        reuse_key: tuple[str, str, str] | None = None,
        chat: str = "",
    ) -> None:
        self.session = session
        self.bridge = bridge
        # (chat, shell asked for, folder): an agent opening the same again gets this one.
        self.reuse_key = reuse_key
        # The chat whose agent opened it; "" for a terminal a person opened.
        self.chat = chat


def get_terminal_manager() -> TerminalManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = TerminalManager()
        return _manager
