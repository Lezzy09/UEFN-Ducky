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
    est = sp.build_preview("Big", jobs, "auto", 14, 5, detail=2)["estimate"]
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
