"""swarm_preview rules: models per seat, distinct detail levels, estimate."""

from __future__ import annotations

import pytest

from backend.tools.panel import swarm_preview as sp


def _job(name, kind="developer", paths=None, steps=2, model="", suggested=""):
    return {"name": name, "purpose": "", "task": "", "kind": kind, "profile": "developer",
            "suggested_model": suggested, "model": model,
            "steps": sp._steps([f"{name} step {i}" for i in range(1, steps + 1)]),
            "paths": paths if paths is not None else [f"app/{name.lower()}/**"]}


def _questions(jobs, **kw):
    return sp.questions_for(jobs, "", 0, 0, 0, **kw)


# ---- questions ----------------------------------------------------------------------------

def test_six_code_jobs_each_get_a_suggested_model():
    jobs = [_job(n) for n in ("Plan engine", "Keeper", "Sidebar", "Chat API", "Agent host", "Store")]
    models = [q for q in _questions(jobs) if q["id"].startswith("model:")]
    assert len(models) == 6
    for q in models:
        assert "(suggested)" in q["options"][0]["label"]
        assert q["options"][0]["id"] != "other"


def test_lead_model_is_the_fallback_for_developer_jobs():
    q = next(q for q in _questions([_job("Keeper")], lead_model="claude:claude-opus-5-5")
             if q["id"] == "model:0")
    assert q["options"][0]["id"] == "claude:claude-opus-5-5"


def test_py_only_job_is_a_developer_job():
    job = _job("Plugins and data safety", kind="writing",
               paths=["ducky_app/backend/plugins/safety.py", "ducky_app/backend/plugins/test_safety.py"])
    fixed = sp.fix_routes([job])[0]
    assert fixed["kind"] == "developer"
    assert fixed["suggested_model"]
    docs = sp.fix_routes([_job("Docs", kind="writing", paths=["docs/guide.md"])])[0]
    assert docs["kind"] == "writing"


def test_only_distinct_detail_levels_are_offered():
    jobs = [_job(n) for n in ("Plan engine", "Keeper", "Sidebar", "Chat API", "Agent host", "Store")]
    detail = next(q for q in _questions(jobs) if q["id"] == "detail")
    assert [o["id"] for o in detail["options"]] == ["2"]  # no kind here has parts: all 4 levels look alike
    mixed = jobs[:3] + [_job("Verse: combat", kind="verse"), _job("UI: HUD", kind="ui")]
    detail = next(q for q in _questions(mixed) if q["id"] == "detail")
    descs = [o["description"] for o in detail["options"]]
    assert len(descs) == len(set(descs)) > 1
    assert "2" in [o["id"] for o in detail["options"]]


# ---- estimate -----------------------------------------------------------------------------

def test_estimate_for_14_opus_seats_of_4_steps(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: (5.0, 0.5, 25.0, 6.25))
    jobs = [_job(f"Job {i}", paths=[f"app/j{i}/**"], steps=4, model="claude:claude-opus-5-5") for i in range(14)]
    est = sp.build_preview("Big", jobs, "auto", 14, 5, edits=[{"interfaces": False}], detail=2)["estimate"]
    assert len(est["seats"]) == 14
    tokens = 14 * 4 * sp.TOKENS_PER_STEP
    assert est["total"]["tokens"] == tokens == 8_400_000
    assert est["total"]["minutes"] == 4 * sp.MINUTES_PER_STEP  # seats run side by side
    seat_cost = (4 * sp.TOKENS_PER_STEP * (1 - sp.OUTPUT_SHARE) * 0.5
                 + 4 * sp.TOKENS_PER_STEP * sp.OUTPUT_SHARE * 25.0) / 1e6
    assert est["total"]["cost_usd"] == pytest.approx(14 * seat_cost, abs=0.1)
    assert est["total"]["text"].startswith("~8.4M tokens · ~40 min")


def test_estimate_without_a_price_has_no_cost(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    est = sp.build_preview("Small", [_job("A")], "auto", 8, 5, detail=2)["estimate"]
    assert est["total"]["cost_usd"] is None
    assert est["seats"]["A lead"] == {"tokens": 2 * sp.TOKENS_PER_STEP, "minutes": 2 * sp.MINUTES_PER_STEP,
                                       "cost_usd": None}


# ---- interfaces first ---------------------------------------------------------------------

CODE4 = ["Setup", "Export", "Store", "Errors"]


def test_four_code_jobs_get_an_interfaces_section_the_others_wait_for(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    p = sp.build_preview("Plugin", [_job(n) for n in CODE4], "auto", 8, 5, detail=2)
    sections = {s["title"]: s for s in p["plan"]["sections"]}
    assert "Interfaces" in sections and sections["Interfaces"]["seat"] == sp.INTEGRATOR
    assert sections["Interfaces"]["steps"][0]["content"].startswith("Interfaces:")
    others = [s for s in p["plan"]["sections"] if s["seat"] != sp.INTEGRATOR]
    assert len(others) == 4 and all(s["after"] == [f"{sp.INTEGRATOR}#1"] for s in others)
    assert sp.INTEGRATOR in p["jobs"]
    # interfaces first, then the 2-step seats side by side, then the Integrator wires them in
    assert p["estimate"]["total"]["minutes"] == 4 * sp.MINUTES_PER_STEP


def test_interfaces_can_be_turned_off_and_need_three_code_seats(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    off = sp.build_preview("Plugin", [_job(n) for n in CODE4], "auto", 8, 5, edits=[{"interfaces": False}])
    assert sp.INTEGRATOR not in off["lanes"]
    two = sp.build_preview("Plugin", [_job(n) for n in CODE4[:2]] + [_job("Story", kind="narrative")],
                           "auto", 8, 5)
    assert sp.INTEGRATOR not in two["lanes"]


# ---- integrator glue ----------------------------------------------------------------------

REPO = ["plugins/pk/plugin.json", "plugins/pk/README.md", "plugins/pk/backend/__init__.py",
        "plugins/pk/backend/setup.py", "plugins/pk/backend/export/run.py", "plugins/pk/backend/store/api.py",
        "plugins/pk/ui/index.html", "plugins/pk/ui/app.js", "plugins/pk/ui/css/app.css"]


def test_integrator_owns_the_glue_and_no_other_lane_holds_it(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    jobs = [_job("Setup", paths=["plugins/pk/backend/**"]), _job("Export", paths=["plugins/pk/backend/export/**"]),
            _job("Store", paths=["plugins/pk/backend/store/**"]), _job("Panel", paths=["plugins/pk/ui/**"])]
    p = sp.build_preview("Plugin", jobs, "auto", 8, 5, detail=2, repo_files=REPO)
    glue = ["plugins/pk/plugin.json", "plugins/pk/backend/__init__.py", "plugins/pk/ui/index.html"]
    assert p["lanes"][sp.INTEGRATOR] == glue
    for seat, lane in p["lanes"].items():
        if seat != sp.INTEGRATOR:
            assert not any(sp.lane_match(pat, g) for pat in lane for g in glue), (seat, lane)
    # carved lanes still hold everything else they had
    assert set(p["lanes"]["Setup lead"]) == {"plugins/pk/backend/export/**", "plugins/pk/backend/setup.py",
                                             "plugins/pk/backend/store/**"}
    assert set(p["lanes"]["Panel lead"]) == {"plugins/pk/ui/app.js", "plugins/pk/ui/css/**"}
    integ = next(s for s in p["plan"]["sections"] if s["seat"] == sp.INTEGRATOR)
    assert integ["steps"][0]["content"].startswith("Interfaces:")  # its first point
    assert set(integ["steps"][1]["after"]) == {"Setup lead#2", "Export lead#2", "Store lead#2", "Panel lead#2"}
    assert p["jobs"][sp.INTEGRATOR]["paths"] == glue


# ---- oversized steps ----------------------------------------------------------------------

def test_a_four_outcome_step_is_flagged_and_splits_into_four(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    job = _job("Store", kind="narrative")
    job["steps"] = sp._steps(["Store: upload, events, deploy and install", "Store: docs"])
    p = sp.build_preview("Ship", [job], "auto", 8, 5, detail=2)
    [flag] = p["oversized"]
    assert flag["step"] == "Store: upload, events, deploy and install" and flag["outcomes"] == 4
    assert flag["chip"] == "Too big: 4 outcomes · Split"
    assert [s["content"] for s in flag["split"]] == ["Store: upload", "Store: events", "Store: deploy",
                                                     "Store: install"]
    split = sp.build_preview("Ship", [job], "auto", 8, 5, detail=2,
                             edits=[{"seat": flag["seat"], "split_step": flag["step"]}])
    assert split["oversized"] == []
    assert [s["content"] for s in split["plan"]["sections"][0]["steps"]][:4] == [s["content"] for s in flag["split"]]
    assert split["tree"][0]["sub_plan"]["total"] == 5


def test_a_step_over_three_file_areas_is_flagged():
    seats = [{"name": "A", "id": "A", "lane": [], "after": [], "steps": [
        {"id": "A#1", "content": "Rewire the panel", "after": [],
         "body": "**Files:** `a/x.py`, `b/y.py`, `c/z.ts` (and notes)."},
        {"id": "A#2", "content": "Fix x, y", "after": [], "body": "Files: a/x.py, a/y.py"}]}]
    [flag] = sp.oversized_steps(seats)
    assert flag["step"] == "Rewire the panel" and flag["areas"] == 3
    assert [s["content"] for s in flag["split"]] == ["Rewire the panel: a", "Rewire the panel: b",
                                                     "Rewire the panel: c"]


# ---- from-plan checks: one live owner per file --------------------------------------------

PANEL = "ducky_app/frontend/ui_web/panel_api.py"
FILES = [PANEL, "ducky_app/frontend/ui_web/chat_rows.py", "ducky_app/frontend/agent_host/turns.py",
         "ducky_app/frontend/settings.py"]


def _plan(chat_extra="", host_after=None, chat_after=None, step_files=f"`{PANEL}`"):
    return {"title": "Speed", "nodes": [
        {"id": "s1", "content": "Chat API", "after": chat_after or [],
         "body_markdown": f"**Files:** `{PANEL}`, `ducky_app/frontend/ui_web/chat_rows.py`{chat_extra}",
         "children": [{"id": "a1", "content": "Split rows", "body_markdown": f"**Files:** {step_files}"},
                      {"id": "a2", "content": "Push rows", "body_markdown": ""}]},
        {"id": "g1", "content": "Agents", "children": [
            {"id": "s2", "content": "Agent host", "after": host_after or [],
             "body_markdown": f"**Files:** `{PANEL}`, `ducky_app/frontend/agent_host/**`",
             "children": [{"id": "b1", "content": "Host turns", "body_markdown": ""}]}]}]}


def test_two_seats_sharing_a_file_without_a_hand_over_conflict():
    out = sp.check_plan(_plan(), FILES)
    assert out["status"] == "needs_answers"
    assert out["conflicts"] == [{"file": PANEL, "seats": ["Chat API", "Agent host"]}]


def test_a_declared_hand_over_with_after_is_ok():
    hand = f"\nHands over: `{PANEL}` → Agent host"
    assert sp.check_plan(_plan(chat_extra=hand, host_after=["a2"]), FILES)["status"] == "ok"
    # the after may name the giver's section too
    assert sp.check_plan(_plan(chat_extra=hand, host_after=["s1"]), FILES)["conflicts"] == []
    # declared, but the taker doesn't wait for it: still two live owners
    assert sp.check_plan(_plan(chat_extra=hand), FILES)["conflicts"][0]["file"] == PANEL


def test_after_cycle_is_reported():
    out = sp.check_plan(_plan(host_after=["a2"], chat_after=["g1"]), FILES)
    assert out["status"] == "needs_answers"
    assert len(out["cycles"]) == 1 and set(out["cycles"][0]) >= {"Host turns", "Push rows"}


def test_a_step_naming_a_file_outside_its_lane_is_reported():
    out = sp.check_plan(_plan(step_files="`ducky_app/frontend/settings.py`, `chat_rows.py`"), FILES)
    assert out["out_of_lane"] == [{"seat": "Chat API", "step": "Split rows", "file": "ducky_app/frontend/settings.py"}]


def _section(sid, name, steps, after=None, files=""):
    return {"id": sid, "content": name, "after": after or [], "body_markdown": f"**Files:** {files}" if files else "",
            "children": [{"id": f"{sid}.{i}", "content": f"{name} {i}", "body_markdown": body}
                         for i, body in enumerate(steps, 1)]}


def test_three_waves_give_widths_6_4_2_and_late_seats_start_later():
    first = [_section(f"w1{c}", f"One {c}", [""]) for c in "abcdef"]
    second = [_section(f"w2{c}", f"Two {c}", [""], after=["w1a"]) for c in "abcd"]
    third = [_section(f"w3{c}", f"Three {c}", [""], after=["w2a"]) for c in "ab"]
    out = sp.check_plan({"nodes": first + second + third}, pc_limit=0)["balance"]
    assert out["waves"] == [6, 4, 2] and out["peak"] == 6
    later = {x["seat"]: x for x in out["start_later"]}
    assert later["Three a"]["wave"] == 3 and later["Three a"]["after"] == ["Two a"]
    assert len(later) == 6 and "One a" not in later
    assert {"seat": "Three a", "into": "Two a"} in out["merge"]
    assert out["summary"].startswith("Peak 6 agents · waves 6 / 4 / 2 · 6 seats start later")
    assert sp.check_plan({"nodes": first + second + third}, pc_limit=4)["balance"]["peak"] == 4


def test_a_ten_step_seat_beside_two_step_seats_gets_a_split_proposal():
    big = _section("big", "Chat API", ["Files: `ui_web/a.py`"] * 5 + ["Files: `agent_host/b.py`"] * 5)
    small = [_section(f"s{i}", f"Small {i}", ["", ""]) for i in range(3)]
    out = sp.check_plan({"nodes": [big, *small]}, pc_limit=0)["balance"]
    [split] = out["split"]
    assert split["seat"] == "Chat API" and split["steps"] == 10
    assert [(p["title"], len(p["steps"])) for p in split["proposal"]] == [("Chat API: ui_web", 5),
                                                                          ("Chat API: agent_host", 5)]
    assert "split Chat API (10 steps)" in out["summary"]


def test_the_job_preview_carries_balance(monkeypatch):
    monkeypatch.setattr(sp, "_price", lambda model: None)
    p = sp.build_preview("Plugin", [_job(n) for n in CODE4], "auto", 8, 5, detail=2, pc_limit=0)
    assert p["balance"]["waves"] == [1, 4, 1]  # Interfaces, the 4 seats, then the wiring step
    assert [x["seat"] for x in p["balance"]["start_later"]] == ["Setup lead", "Export lead", "Store lead", "Errors lead"]


def test_without_a_file_list_lane_patterns_are_compared():
    out = sp.check_plan(_plan())
    assert out["conflicts"] == [{"file": PANEL, "seats": ["Chat API", "Agent host"]}]
