"""Publish must stop before a version bump when the security check fails."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _publish():
    path = Path(__file__).resolve().parents[1] / "release" / "publish_app.py"
    spec = importlib.util.spec_from_file_location("publish_app_gate", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_security_gate_stops_publish(monkeypatch):
    pub = _publish()

    def failed(*_args, **_kwargs):
        class Proc:
            returncode = 1

        return Proc()

    monkeypatch.setattr(pub.subprocess, "run", failed)
    try:
        pub.run_security_gate()
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("a failed security check must stop publish")
