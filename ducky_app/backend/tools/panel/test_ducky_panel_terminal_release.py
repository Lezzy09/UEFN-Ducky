"""A plugin repo's release.py / release.sh waits for a release workflow that holds the plugin."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def plugin_repo(tmp_path, monkeypatch):
    from backend.automations import live_runs
    from backend.tools.panel import panel_ai_plugins

    monkeypatch.setattr(live_runs, "_directory", lambda: tmp_path / "runs")
    monkeypatch.setattr(panel_ai_plugins, "_releases_dir", lambda: tmp_path / "releases")
    repo = tmp_path / "island-media-kit"
    (repo / "scripts").mkdir(parents=True)
    (repo / "plugin.json").write_text(json.dumps({"id": "island-media-kit"}), encoding="utf-8")
    return repo


def _hold(tmp_path, workflow="wf", run="7f3a"):
    from backend.automations import live_runs
    from backend.tools.panel.panel_ai_plugins import start_release_run

    live_runs.start(workflow, run)
    start_release_run("island-media-kit", workflow, run)


def test_release_refusal_finds_the_plugin_from_cwd_or_the_command(plugin_repo, tmp_path):
    from backend.tools.panel.ducky_panel_terminal import release_refusal

    assert release_refusal("python release.py", str(plugin_repo / "scripts")) == ""  # nothing holds it
    _hold(tmp_path)
    msg = release_refusal("python release.py", str(plugin_repo / "scripts"))
    assert "island-media-kit: release workflow 7f3a is running" in msg
    assert release_refusal(f'py -3 "{plugin_repo.as_posix()}/scripts/release.py" --publish', "") == msg
    assert release_refusal("bash ./scripts/release.sh --docker", str(plugin_repo)) == msg
    assert release_refusal("py -3 -m pytest -q", str(plugin_repo)) == ""  # not a release
    assert release_refusal("python prerelease.py", str(plugin_repo)) == ""
    assert release_refusal("python release.py", str(tmp_path)) == ""  # not a plugin repo


def test_release_workflow_runs_its_own_release_step(plugin_repo, tmp_path):
    from backend.automations.runner import _REGISTRY_RUNS
    from backend.tools.panel.ducky_panel_terminal import release_refusal

    _hold(tmp_path)
    token = _REGISTRY_RUNS.set((("wf", "7f3a"),))
    try:
        assert release_refusal("python scripts/release.py --publish", str(plugin_repo)) == ""
    finally:
        _REGISTRY_RUNS.reset(token)


def test_terminal_run_refuses_while_busy_and_runs_when_free(plugin_repo, tmp_path, monkeypatch):
    from backend.tools.panel import ducky_panel_terminal as term

    ran: list[str] = []
    mgr = SimpleNamespace(
        get_session=lambda sid: SimpleNamespace(cwd=str(plugin_repo)),
        run_agent_command=lambda sid, command, **kw: ran.append(command) or {"ok": True, "exit_code": 0},
    )
    monkeypatch.setattr(term, "_terminal_manager", lambda: mgr)
    monkeypatch.setattr(term, "_terminal_chat", lambda conv_id: "")

    free = json.loads(term.ducky_terminal_run("s1", "python scripts/release.py --publish"))
    assert free["ok"] is True and ran == ["python scripts/release.py --publish"]
    _hold(tmp_path)
    busy = json.loads(term.ducky_terminal_run("s1", "python scripts/release.py --publish"))
    assert busy["ok"] is False and "release workflow 7f3a is running" in busy["error"] and len(ran) == 1
