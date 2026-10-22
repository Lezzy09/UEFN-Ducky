"""An agent's PowerShell command reports its exit code, so it never waits until it times out.

The old marker wrote "$LASTEXITCODE__" inside a string, which PowerShell reads as a
variable named LASTEXITCODE__: it printed no code, the done pattern never matched,
and every agent or workflow command in a PowerShell terminal hung until its timeout.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from frontend.ui_web.terminal.session import _DONE_RE, TerminalSession, agent_command_output

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
needs_powershell = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL, reason="needs Windows PowerShell"
)


def _wrapped(command: str) -> str:
    return TerminalSession(shell="powershell", cwd=".")._wrap_agent_command(command, background=False)


def _run(script: str) -> str:
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=90,
    )
    return result.stdout


def _reported_code(script: str) -> int:
    out = _run(script)
    match = _DONE_RE.search(out)
    assert match, out
    return int(match.group(1))


def test_the_command_is_submitted_with_a_bare_carriage_return():
    wrapped = _wrapped("echo hello")
    assert wrapped.endswith("\r") and not wrapped.endswith("\r\n")
    background = TerminalSession(shell="powershell", cwd=".")._wrap_agent_command("long", background=True)
    assert "; Invoke-Expression 'long'; foreach" in background and background.endswith("; \r")


@needs_powershell
def test_a_trailing_comment_or_quotes_never_eat_the_done_marker():
    assert _reported_code(_wrapped("echo hi  # a note").rstrip("\r")) == 0
    # A failed statement doesn't skip the next one, as when the command is typed.
    out = _run(_wrapped("no_such_command_ducky; Write-Output after-it").rstrip("\r"))
    assert "after-it" in out and _DONE_RE.search(out).group(1) == "0", out
    out = _run(_wrapped("Write-Output \"it's, it’s\"").rstrip("\r"))
    assert "it's, it’s" in out and _DONE_RE.search(out), out


@needs_powershell
def test_a_cd_or_variable_from_an_agent_command_stays(tmp_path):
    out = _run(_wrapped(f"Set-Location '{tmp_path}'; $kept = 7").rstrip("\r") + "; Write-Output \"at=$((Get-Location).Path) kept=$kept\"")
    assert f"at={tmp_path} kept=7" in out, out


def test_the_typed_line_itself_never_looks_done():
    assert _DONE_RE.search(_wrapped("echo hello")) is None


@needs_powershell
def test_a_cmdlet_that_succeeds_reports_0():
    assert _reported_code(_wrapped("echo hello").rstrip("\r")) == 0


@needs_powershell
def test_a_cmdlet_that_fails_reports_1():
    assert _reported_code(_wrapped(r"Get-Item C:\no\such\path_ducky_xyz").rstrip("\r")) == 1


@needs_powershell
def test_a_native_command_reports_its_own_exit_code():
    assert _reported_code(_wrapped("cmd /c exit 3").rstrip("\r")) == 3


@needs_powershell
def test_an_earlier_native_failure_is_not_reported_for_a_later_success():
    assert _reported_code("cmd /c exit 5; " + _wrapped("echo fine").rstrip("\r")) == 0


def test_a_negative_windows_exit_code_still_counts_as_done():
    match = _DONE_RE.search("__DUCKY_DONE__-1073741819__")
    assert match and int(match.group(1)) == -1073741819


def test_bash_commands_print_a_begin_mark_the_echo_cannot_spell():
    wrapped = TerminalSession(shell="bash", cwd=".")._wrap_agent_command("ls", background=False)
    assert wrapped == (
        "printf '__DUCKY_%s__\\n' BEGIN; GIT_PAGER=cat GH_PAGER=cat GIT_EDITOR=true GH_PROMPT_DISABLED=1 eval ls; "
        "echo __DUCKY_DONE__$?__\r\n"
    )
    assert "__DUCKY_BEGIN__" not in wrapped and "__DUCKY_BEGIN__" not in _wrapped("ls")


def test_a_bash_comment_or_bang_stays_inside_the_command():
    wrapped = TerminalSession(shell="bash", cwd=".")._wrap_agent_command('git commit -m "fix!"  # done', background=False)
    assert "eval 'git commit -m \"fix!\"  # done'; echo __DUCKY_DONE__$?__" in wrapped
    background = TerminalSession(shell="bash", cwd=".")._wrap_agent_command("npm run dev", background=True)
    assert background == "(GIT_PAGER=cat GH_PAGER=cat GIT_EDITOR=true GH_PROMPT_DISABLED=1 eval 'npm run dev') &\r\n"


@needs_powershell
def test_an_agent_command_gets_no_pager_or_editor_and_the_shell_keeps_its_own():
    # Oct 22 2026: `git log` waited in less and `git commit` in vim until the agent timed out.
    script = (
        "$env:GIT_PAGER = 'mine'; Remove-Item Env:GIT_EDITOR, Env:GH_PAGER -ErrorAction SilentlyContinue; "
        + _wrapped("cmd /c echo inside=%GIT_PAGER%/%GIT_EDITOR%/%GH_PAGER%").rstrip("\r")
        + "; Write-Output \"after=$env:GIT_PAGER/$env:GIT_EDITOR/$env:GH_PAGER\""
    )
    out = _run(script)
    assert "inside=cat/true/cat" in out and "after=mine//" in out, out


def test_the_agent_reads_only_the_command_output_without_escape_codes():
    # Shaped like a real PowerShell console: PSReadLine colors and redraws the typed
    # line (cursor moves, then the line again), then the output, then the next prompt.
    typed = _wrapped("echo hello").rstrip("\r")
    raw = (
        "\x1b[1t\x1b[?1004hPS C:\\p> \x1b[?25l\x1b[1;64H\x1b[93mecho\x1b[39;49m"
        + typed.replace("echo", "\x1b[93mecho\x1b[0m") + "\x1b[2;107H\x1b[?25h"
        + "\r\n__DUCKY_BEGIN__\r\nhello\r\n\x1b[32mworld\x1b[0m\r\n"
        + "__DUCKY_DONE__0__\r\n\x1b]0;PowerShell\x07PS C:\\p> "
    )
    assert agent_command_output(raw) == "hello\nworld"


def test_a_redrawn_progress_line_shows_what_was_written_last():
    raw = "__DUCKY_BEGIN__\r\n 10%\r 55%\r100% done\r\n__DUCKY_DONE__0__\r\n"
    assert agent_command_output(raw) == "100% done"


def test_an_earlier_command_never_answers_for_a_command_still_running():
    raw = (
        "__DUCKY_BEGIN__\r\nold output\r\n__DUCKY_DONE__0__\r\nPS> "
        "__DUCKY_BEGIN__\r\nstill building...\r\n"
    )
    assert agent_command_output(raw) == "still building..."


@needs_powershell
def test_a_real_powershell_terminal_finishes_and_reports_success(tmp_path):
    session = TerminalSession(shell="powershell", cwd=str(tmp_path))
    try:
        session.spawn()
    except Exception as exc:  # noqa: BLE001 - no console host available here
        pytest.skip(f"cannot start a PowerShell terminal here: {exc}")
    try:
        result = session.run_command("echo ducky-pty-ok", timeout_s=60)
        assert result["ok"], result
        assert result["exit_code"] == 0
        assert result["output_tail"] == "ducky-pty-ok", result
        failed = session.run_command(r"Get-Item C:\no\such\path_ducky_xyz", timeout_s=60)
        assert failed["ok"] and failed["exit_code"] == 1, failed
    finally:
        session.kill()


@needs_powershell
@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_git_log_and_a_commit_without_a_message_never_wait_on_a_pager_or_editor(tmp_path, monkeypatch):
    monkeypatch.delenv("GIT_EDITOR", raising=False)
    monkeypatch.delenv("GIT_PAGER", raising=False)
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, check=True)  # noqa: E731
    git("init", "-q")
    for i in range(40):  # more than a screen, so git would start less
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", f"c{i}")
    session = TerminalSession(shell="powershell", cwd=str(tmp_path))
    session.resize(80, 10)
    try:
        session.spawn()
    except Exception as exc:  # noqa: BLE001 - no console host available here
        pytest.skip(f"cannot start a PowerShell terminal here: {exc}")
    try:
        log = session.run_command("git log --oneline", timeout_s=30)
        assert log["ok"] and log["exit_code"] == 0 and log["output_tail"].count("\n") >= 39, log
        commit = session.run_command("git -c user.name=t -c user.email=t@example.invalid commit --allow-empty", timeout_s=30)
        assert commit["ok"] and commit["exit_code"] == 1 and "empty commit message" in commit["output_tail"], commit
    finally:
        session.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="needs Git Bash on Windows")
def test_ctrl_c_from_the_person_ends_the_agents_wait(tmp_path):
    # Bash drops the rest of the line on Ctrl+C, done marker included: the agent used to
    # wait out its whole timeout after the person had stopped its command.
    import threading
    import time

    session = TerminalSession(shell="bash", cwd=str(tmp_path))
    try:
        session.spawn()
    except Exception as exc:  # noqa: BLE001 - no Git Bash here
        pytest.skip(f"cannot start a bash terminal here: {exc}")
    try:
        assert session.run_command("echo ready", timeout_s=60)["ok"]
        threading.Timer(2.0, lambda: session.write("\x03")).start()
        started = time.time()
        result = session.run_command("sleep 60", timeout_s=120)
        assert time.time() - started < 15, result
        assert not result["ok"] and "Ctrl+C" in result["error"], result
        assert session.run_command("echo after", timeout_s=60)["output_tail"] == "after"
    finally:
        session.kill()


@needs_powershell
def test_a_timed_out_command_still_running_gets_no_typed_commands(tmp_path):
    session = TerminalSession(shell="powershell", cwd=str(tmp_path))
    try:
        session.spawn()
    except Exception as exc:  # noqa: BLE001 - no console host available here
        pytest.skip(f"cannot start a PowerShell terminal here: {exc}")
    try:
        assert session.run_command("echo ready", timeout_s=60)["ok"]
        slow = session.run_command("ping -n 20 127.0.0.1", timeout_s=2)
        assert slow["error"] == "command timed out", slow
        refused = session.run_command("echo next", timeout_s=10)
        assert not refused["ok"] and "ping.exe" in refused["error"] and "ducky_terminal_close" in refused["hint"], refused
    finally:
        session.kill()
