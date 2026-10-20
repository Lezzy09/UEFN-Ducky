"""Oversized nested-tool spill: stub in context, file on disk, prune, sandbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent import tool_spills as ts


@pytest.fixture
def spill_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "UEFN-Ducky"
    root.mkdir()
    monkeypatch.setattr(ts, "resolve_app_data_dir", lambda for_write=False: root)
    return root


def test_15k_result_stubs_and_file(spill_root: Path) -> None:
    payload = "x" * 15_000
    out = ts.inline_or_spill("unreal__describe_toolset", payload)
    assert len(out) < 12_000
    stub = json.loads(out)
    assert stub["truncated"] is True
    assert stub["chars"] == 15_000
    assert stub["preview"] == payload[: ts.PREVIEW_CHARS]
    path = Path(stub["path"])
    assert path.is_file()
    assert "tool_spills" in str(path).replace("\\", "/")
    assert path.read_text(encoding="utf-8") == payload
    assert payload not in out or len(out) < len(payload)


def test_small_result_stays_inline(spill_root: Path) -> None:
    text = "hello"
    assert ts.inline_or_spill("demo__ping", text) == text


def test_prune_keeps_n(spill_root: Path) -> None:
    for i in range(25):
        ts.spill_tool_result("demo__tool", f"payload-{i}-" + ("y" * 100))
    files = list((spill_root / "tool_spills").glob("*.txt"))
    assert len(files) <= ts.KEEP_FILES


def test_reader_offset_page(spill_root: Path) -> None:
    stub = json.loads(ts.spill_tool_result("demo__page", "abcdefghij" * 20))
    page = ts.read_tool_spill(stub["name"], offset=10, max_chars=5)
    body = Path(stub["path"]).read_text(encoding="utf-8")
    assert page["ok"] is True
    assert page["chunk"] == body[10:15]
    assert page["truncated"] is True


def test_path_escape_refused(spill_root: Path) -> None:
    ts.spill_tool_result("demo__ok", "payload")
    with pytest.raises(ValueError):
        ts.read_tool_spill("../secrets.txt")
    with pytest.raises(ValueError):
        ts.read_tool_spill(str(spill_root / "tool_spills" / "nope.txt"))
    with pytest.raises(ValueError):
        ts.read_tool_spill("not-a-file.txt")


def test_spill_stub_survives_llm_envelope(spill_root: Path) -> None:
    """Don't let the model cap turn a spill into an opaque truncation mark."""
    from backend.agent.serialization import format_tool_result_for_llm
    from backend.agent.tools import ToolCallResult, API_TOOL_RESULT_MAX

    stub = ts.inline_or_spill("unreal__describe_toolset", "n" * 15_000)
    payload = ToolCallResult(ok=True, tool="unreal__describe_toolset", data=stub).to_json_str()
    for fmt in ("toon", "json"):
        out = format_tool_result_for_llm("unreal__describe_toolset", payload, fmt=fmt)
        assert len(out) <= API_TOOL_RESULT_MAX + 200  # toon can be slightly off the json cap
        assert "truncated" in out.lower() or "spill" in out.lower()
        parsed = json.loads(stub)
        assert parsed["name"] in out
        assert "…" not in out or parsed["name"] in out


@pytest.mark.parametrize("fmt", ["toon", "json"])
def test_spill_page_and_skill_section_reach_the_model_whole(spill_root: Path, fmt: str) -> None:
    """Oct 20 2026: at a 2,200 cap an 8,000-char spill page arrived as 1,290 chars and a 10k
    skill section as 1,076, so the agent re-read both again and again."""
    from backend.agent.serialization import format_tool_result_for_llm
    from backend.agent.tools import ToolCallResult

    rows = json.dumps([{"id": f"wf-{i:04d}", "name": f"Workflow {i}", "folder": ""} for i in range(900)])
    stub = json.loads(ts.inline_or_spill("list_workflows", rows))
    page = ts.read_tool_spill(stub["name"], offset=0)  # default = one whole page
    assert len(page["chunk"]) == ts.READ_MAX_CHARS
    last_id = page["chunk"].rsplit('"wf-', 1)[1][:4]
    via_call_tool = ToolCallResult(ok=True, tool="ducky_call_tool", data=json.dumps(page)).to_json_str()
    out = format_tool_result_for_llm("ducky_call_tool", via_call_tool, fmt=fmt)
    assert "omitted" not in out and f"wf-{last_id}" in out

    body = "## Spawning\n" + "Use SpawnProp with a creative_prop_asset. " * 230 + "END-OF-SECTION"
    skill = ToolCallResult(ok=True, tool="skill_read_subskill", data={"body": body}).to_json_str()
    out = format_tool_result_for_llm("skill_read_subskill", skill, fmt=fmt)
    assert len(body) > 9_000 and "omitted" not in out and "END-OF-SECTION" in out
