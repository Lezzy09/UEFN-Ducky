"""proc_exec — keep_stdin_open hands out a line writer for the whole turn."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.coding_agents import proc_exec

_ECHO = (
    "import sys\n"
    "for line in sys.stdin:\n"
    "    print('got:' + line.strip(), flush=True)\n"
    "print('eof', flush=True)\n"
)


def _run(tmp_path, conv_id, **kw):
    script = tmp_path / "echo.py"
    script.write_text(_ECHO, encoding="utf-8")
    lines: list[str] = []
    result = proc_exec.run_streaming_process(
        argv=[sys.executable, str(script)],
        cwd=str(tmp_path),
        env_extra={},
        conv_id=conv_id,
        on_line=lines.append,
        timeout_s=kw.pop("timeout_s", 20.0),
        **kw,
    )
    return result, lines


def test_default_closes_stdin_after_initial_input(tmp_path):
    result, lines = _run(tmp_path, "stdin-default", stdin_data="first\n")
    assert result.returncode == 0
    assert result.stdin_writer is None
    assert lines == ["got:first", "eof"]
    assert proc_exec.get_stdin_writer("stdin-default") is None


def test_keep_open_takes_two_writes_then_eof_on_close(tmp_path):
    def _drive(writer: proc_exec.StdinWriter) -> None:
        def _go() -> None:
            assert proc_exec.get_stdin_writer("stdin-open") is writer
            assert writer.write_line("one")
            assert writer.write_line("two")
            time.sleep(0.2)
            writer.close()

        threading.Thread(target=_go, daemon=True).start()

    result, lines = _run(
        tmp_path, "stdin-open", stdin_data="first\n", keep_stdin_open=True, on_stdin_writer=_drive
    )
    assert result.returncode == 0
    assert lines == ["got:first", "got:one", "got:two", "eof"]
    assert result.stdin_writer is not None and result.stdin_writer.closed
    assert result.stdin_writer.write_line("late") is False
    assert proc_exec.get_stdin_writer("stdin-open") is None


# Writes past the pipe buffer before it reads stdin, like Claude Code with stream-json input.
_TALKS_FIRST = (
    "import sys\n"
    "sys.stdout.write('x' * 65536 + '\\n'); sys.stdout.flush()\n"
    "print('read', len(sys.stdin.readline()), flush=True)\n"
)


def _run_script(tmp_path, source, conv_id, **kw):
    script = tmp_path / f"{conv_id}.py"
    script.write_text(source, encoding="utf-8")
    lines: list[str] = []
    out: dict = {}

    def _go() -> None:
        out["result"] = proc_exec.run_streaming_process(
            argv=[sys.executable, str(script)], cwd=str(tmp_path), env_extra={}, conv_id=conv_id,
            on_line=lines.append, timeout_s=kw.pop("timeout_s", 20.0), **kw,
        )

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join(15)
    assert not t.is_alive(), "run_streaming_process deadlocked"
    return out["result"], lines


def test_a_big_prompt_reaches_a_cli_that_writes_before_it_reads(tmp_path):
    prompt = "p" * 200_000 + "\n"
    for keep in (True, False):
        result, lines = _run_script(tmp_path, _TALKS_FIRST, f"talks-first-{keep}", stdin_data=prompt,
                                    keep_stdin_open=keep)
        assert result.returncode == 0
        assert lines[-1] == f"read {len(prompt)}"


def test_stop_works_while_the_prompt_is_still_being_written(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    result, _lines = _run_script(tmp_path, "import time\ntime.sleep(60)\n", "never-reads",
                                 stdin_data="p" * 200_000 + "\n", keep_stdin_open=True, cancel=cancel)
    assert result.cancelled and time.monotonic() - started < 10
    assert result.stdin_writer.closed


def test_the_prompt_goes_out_before_any_later_line(tmp_path):
    def _drive(writer: proc_exec.StdinWriter) -> None:
        assert writer.write_line("second")
        writer.close()

    result, lines = _run(tmp_path, "stdin-order", stdin_data="x" * 100_000 + "\n", keep_stdin_open=True,
                         on_stdin_writer=_drive)
    assert result.returncode == 0
    assert [line[:6] for line in lines] == ["got:xx", "got:se", "eof"]


def test_cancel_closes_stdin(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    result, _lines = _run(tmp_path, "stdin-cancel", keep_stdin_open=True, cancel=cancel, timeout_s=0.0)
    assert result.cancelled is True
    assert result.stdin_writer.closed
    assert proc_exec.get_stdin_writer("stdin-cancel") is None
