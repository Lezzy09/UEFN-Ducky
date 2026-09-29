from unittest.mock import Mock

from backend.automations import runner
from backend.automations.store import save_workflow


def graph(nodes, edges):
    return save_workflow({"name": "Inputs", "graph": {"nodes": nodes, "edges": edges}})


def test_pipeline_without_chat_starts_at_action_and_receives_request(monkeypatch):
    run = Mock(return_value={"ok": True, "result": {"text": "Completed", "files": []}})
    monkeypatch.setattr(runner, "_pipeline_agent", run)
    monkeypatch.setattr(runner, "_ensure_pipeline_group", lambda *a: None)
    wf = graph([{"id": "a", "type": "pipeline.agent", "config": {}}, {"id": "end", "type": "pipeline.finish", "config": {}}], [{"source": "a", "target": "end"}])
    result = runner.run_workflow(wf["id"], prompt="Build a red tower", files=[{"path": "input.png"}])
    assert result["ok"]
    assert result["text"] == "Completed"
    assert [step["id"] for step in result["steps"]] == ["a", "end"]
    assert run.call_args.args[1]["prompt"] == "Build a red tower"


def test_chat_input_preserves_prompt_and_files(monkeypatch):
    seen = {}
    def inspect(cfg, payload):
        seen.update(payload)
        return {"ok": True}
    monkeypatch.setattr(runner, "_pipeline_agent", inspect)
    monkeypatch.setattr(runner, "_ensure_pipeline_group", lambda *a: None)
    wf = graph([{"id": "in", "type": "start.chat"}, {"id": "a", "type": "pipeline.agent"}], [{"source": "in", "target": "a"}])
    result = runner.run_workflow(wf["id"], prompt="Use this picture", files=[{"path": "picture.png"}], caller_conv_id="user-chat")
    assert result["ok"]
    assert seen["prompt"] == "Use this picture"
    assert seen["files"][0]["path"] == "picture.png"
    assert seen["caller_conv_id"] == "user-chat"


def test_return_to_user_ends_path_and_keeps_result_in_test_log():
    wf = graph([{"id": "end", "type": "pipeline.finish", "config": {"message": "Here is your result"}}, {"id": "after", "type": "tool.call", "config": {"name": "must-not-run"}}], [{"source": "end", "target": "after"}])
    out = runner.run_workflow(wf["id"])
    assert out["ok"]
    assert out["text"] == "Here is your result"
    assert [step["id"] for step in out["steps"]] == ["end"]


def test_end_workflow_stops_without_posting_a_reply():
    wf = graph([{"id": "end", "type": "flow.end"}, {"id": "after", "type": "tool.call", "config": {"name": "must-not-run"}}], [{"source": "end", "target": "after"}])
    out = runner.run_workflow(wf["id"])
    assert out["ok"] and out["text"] == ""
    assert [step["id"] for step in out["steps"]] == ["end"]


def test_event_trigger_does_not_run_unrelated_roots():
    nodes = {"manual": {"id": "manual", "type": "start.manual"}, "wait": {"id": "wait", "type": "flow.wait"}}
    assert runner._start_ids(nodes, trigger_id="email.received", starter_id="") == []


def test_cyclic_graph_without_start_reports_how_to_fix_it():
    wf = graph([{"id": "a", "type": "flow.wait"}, {"id": "b", "type": "flow.wait"}], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}])
    out = runner.run_workflow(wf["id"])
    assert not out["ok"] and "start" in out["error"].lower()
