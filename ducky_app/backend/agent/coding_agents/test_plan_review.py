"""Plans that can be followed: small steps with a description, or the tool says which to fix."""

from __future__ import annotations

from backend.agent.coding_agents.plans import PLAN_PROTOCOL, plan_review, with_plan_review


def _plan(*nodes: dict) -> dict:
    return {"nodes": list(nodes)}


def test_a_step_that_hides_many_checks_is_flagged_and_small_described_steps_pass() -> None:
    # Oct 11 2026: one step held fifteen checks for two hours; the plan read 15/19 throughout.
    plan = _plan(
        {"id": "s", "content": "Acceptance", "status": "in_progress", "body_markdown": "",
         "children": [
             {"id": "e2e", "content": "Check all original feature paths end to end in the usable panel.",
              "status": "in_progress", "body_markdown": "Run the panel acceptance."},
             {"id": "mov", "content": "Export the test project as a 15 s MOV", "status": "pending",
              "body_markdown": "Do: render it.\nDone when: imk_render_get says done.\nExample: 15.0 s, 30 fps."},
             {"id": "old", "content": "Check every screen", "status": "completed", "body_markdown": ""},
         ]},
    )
    issues = plan_review(plan)
    assert {"n": "1", "issue": "Section has no description: add one line saying what it delivers."} in issues
    assert {"n": "1.1", "issue": "Too big for one step: split it into one step per feature or check."} in issues
    assert not any(i["n"] in ("1.2", "1.3") for i in issues)  # small and described; finished steps are left alone


def test_long_titles_and_missing_descriptions_are_named() -> None:
    plan = _plan({"id": "a", "content": "x" * 140, "status": "pending", "body_markdown": ""})
    assert [i["issue"].split(":")[0] for i in plan_review(plan)] == ["Title too long", "No description"]


def test_the_tool_result_carries_the_review_only_when_needed() -> None:
    good = _plan({"id": "a", "content": "Export the MOV", "status": "pending", "body_markdown": "Do it. Done when: done."})
    assert with_plan_review({"ok": True}, good) == {"ok": True}
    bad = _plan({"id": "a", "content": "Test everything", "status": "pending", "body_markdown": ""})
    out = with_plan_review({"ok": True}, bad)
    assert len(out["plan_review"]) == 2 and "ducky_update_plan" in out["plan_review_hint"]


def test_every_prompt_gets_the_sizing_rule_without_braces() -> None:
    # PLAN_PROTOCOL is placed into prompt templates that are .format()-ted later.
    assert "15–30 minutes" in PLAN_PROTOCOL and "one step per feature or check" in PLAN_PROTOCOL
    assert "{" not in PLAN_PROTOCOL and "}" not in PLAN_PROTOCOL
