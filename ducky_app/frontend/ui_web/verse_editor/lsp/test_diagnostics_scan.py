"""Tests that incremental scans skip when nothing is stale."""

from __future__ import annotations

from pathlib import Path

from frontend.ui_web.verse_editor.lsp import diagnostics_cache
from frontend.ui_web.verse_editor.lsp.diagnostics_scan import scan_project_verse_diagnostics


def test_incremental_scan_skips_when_cache_fresh(tmp_path: Path, monkeypatch):
    content = tmp_path / "Content"
    content.mkdir()
    verse = content / "ok.verse"
    verse.write_text("using { /Fortnite.com/Devices }\n", encoding="utf-8")

    diagnostics_cache.clear(str(tmp_path))
    cache = diagnostics_cache.load(str(tmp_path))
    diagnostics_cache.apply_file(
        str(tmp_path),
        cache,
        "content/ok.verse",
        diagnostics_cache.fingerprint(verse),
        {"errors": 0, "warnings": 0, "items": []},
    )

    def _boom(*_a, **_k):
        raise AssertionError("ephemeral verse-lsp must not start when nothing is stale")

    monkeypatch.setattr(
        "frontend.ui_web.verse_editor.lsp.diagnostics_scan.LspStdioSession",
        _boom,
    )

    events: list[dict] = []

    def on_progress(**kwargs):
        events.append(dict(kwargs))

    result = scan_project_verse_diagnostics(str(tmp_path), full=False, on_progress=on_progress)
    assert result["scanned"] == 0
    assert result["files"]
    assert events == []


def test_full_scan_still_announces_started(tmp_path: Path, monkeypatch):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "ok.verse").write_text("x\n", encoding="utf-8")
    diagnostics_cache.clear(str(tmp_path))

    class FakeSession:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            return None

        def request(self, *_a, **_k):
            raise RuntimeError("stop after started")

        def notify(self, *_a, **_k):
            return None

        def stop(self):
            return None

        def is_alive(self):
            return False

        def file_uri(self, rel: str = "") -> str:
            return f"file:///{rel}"

    monkeypatch.setattr(
        "frontend.ui_web.verse_editor.lsp.diagnostics_scan.LspStdioSession",
        FakeSession,
    )
    monkeypatch.setattr(
        "frontend.ui_web.verse_editor.lsp.diagnostics_scan.discover_verse_workspace",
        lambda _root: {"workspace_folders": [{"path": str(tmp_path), "name": "t"}], "watch_files": []},
    )

    events: list[str] = []

    def on_progress(**kwargs):
        events.append(str(kwargs.get("phase") or ""))

    try:
        scan_project_verse_diagnostics(str(tmp_path), full=True, on_progress=on_progress)
    except RuntimeError:
        pass
    assert "started" in events


_S68 = {
    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 2}},
    "severity": 1,
    "message": "vErr:S68: Use # for line comment, not //",
}


def test_session_keeps_a_syntax_error_after_an_empty_publish():
    import threading

    from frontend.ui_web.verse_editor.lsp.stdio_session import LspStdioSession, is_syntax_error

    s = object.__new__(LspStdioSession)
    s._lock, s._inbound, s._pending = threading.Lock(), [], {}
    s._diag_by_uri, s._syntax_by_uri = {}, {}
    uri = "file:///c%3A/p/Content/a.verse"
    for diags in ([_S68], []):
        s._dispatch({"method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": diags}})
    assert s.published_diagnostics(uri) == []
    assert s.syntax_errors("file:///C:/p/Content/a.verse") == [_S68]
    assert not is_syntax_error({"severity": 1, "message": "vErr:T12: wrong type"})
    assert not is_syntax_error({**_S68, "severity": 2})


def test_scan_does_not_call_a_file_clean_after_verse_lsp_reported_a_syntax_error(tmp_path: Path, monkeypatch):
    # Oct 17 2026: verse-lsp published 1, 0, 1, 1, 0 errors for one unchanged file; the
    # full scan read an empty set and recorded broken Verse as 0 errors.
    content = tmp_path / "Content"
    content.mkdir()
    (content / "bad.verse").write_text("// not verse\n", encoding="utf-8")
    diagnostics_cache.clear(str(tmp_path))

    class FlakySession:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            return None

        def request(self, method, *_a, **_k):
            return {"items": []} if method == "textDocument/diagnostic" else {}

        def notify(self, *_a, **_k):
            return None

        def stop(self):
            return None

        def is_alive(self):
            return True

        def file_uri(self, rel: str = "") -> str:
            return f"file:///{rel}"

        def diagnostic_uri_count(self):
            return 99

        def published_diagnostics(self, _uri):
            return []  # the read lands on verse-lsp's false empty set

        def diagnostics_for_uri(self, _uri):
            return []

        def syntax_errors(self, _uri):
            return [_S68]

    monkeypatch.setattr("frontend.ui_web.verse_editor.lsp.diagnostics_scan.LspStdioSession", FlakySession)
    monkeypatch.setattr(
        "frontend.ui_web.verse_editor.lsp.diagnostics_scan.discover_verse_workspace",
        lambda _root: {"workspace_folders": [{"path": str(tmp_path), "name": "t"}], "watch_files": []},
    )
    result = scan_project_verse_diagnostics(str(tmp_path), full=True)
    bad = [f for f in result["files"] if f["path"].endswith("bad.verse")]
    assert bad and bad[0]["errors"] == 1
    assert bad[0]["items"][0]["message"].startswith("vErr:S68")
