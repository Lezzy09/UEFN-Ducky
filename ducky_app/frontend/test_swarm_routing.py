"""Swarm routing: job kind → template profile + model."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from frontend import agent_profiles
from frontend import favorite_models as fm
from frontend import swarm_routing as sr

ONE_JOB_PER_ROW = {
    "narrative": "Narrative: quest dialogue",
    "research": "Research competitor islands",
    "concept": "Concept: art direction for the hub",
    "modeling": "Modeling: castle mesh in Blender",
    "material": "Texture and shader pass on rocks",
    "verse": "Code: gameplay round logic in Verse",
    "ui": "HUD: score widget",
    "level": "Level: arena layout",
    "npc": "NPC: creature patrols",
    "vfx": "VFX: Niagara sparks",
    "sound": "Sound: music and audio cues",
    "rig": "Rigging the dragon skeleton",
    "animation": "Animation: idle and run cycles",
    "video": "Video: launch trailer",
    "writing": "Writing: docs for the shop",
    "test": "QA: test the spawn pads",
    "review": "Review the changeset",
    "app": "Backend: SQLite store",
}


def test_every_row_has_a_job():
    assert set(ONE_JOB_PER_ROW) == {row.kind for row in sr.JOB_KINDS}


@pytest.mark.parametrize("kind,text", sorted(ONE_JOB_PER_ROW.items()))
def test_one_job_per_row(kind, text):
    row = sr.job_kind(kind)
    got = sr.route(text)
    assert got["kind"] == kind, got
    assert got["profile_id"] == row.profile_id
    assert got["model"] == row.model and got["model"]
    assert got["why"].startswith("matched")


def test_narrative_runs_on_developer_with_its_own_model():
    got = sr.route("Narrative: quest dialogue")
    assert got["kind"] == "narrative"
    assert got["profile_id"] == "developer"
    assert got["model"] == sr.job_kind("narrative").model


def test_explicit_kind_wins_over_keywords():
    got = sr.route("Narrative: quest dialogue", kind="Test")
    assert (got["kind"], got["profile_id"]) == ("test", "tester")
    assert "given" in got["why"]


def test_unknown_explicit_kind_keeps_its_name_on_developer():
    got = sr.route("anything", kind="localization")
    assert (got["kind"], got["profile_id"], got["model"]) == ("localization", "developer", "")


def test_no_match_falls_back_to_developer():
    got = sr.route("Tidy things up")
    assert (got["kind"], got["profile_id"]) == ("developer", "developer")


def test_python_job_routes_to_developer():
    assert sr.route("Python: settings migration")["profile_id"] == "developer"


def test_missing_specialist_profile_falls_back_to_developer():
    got = sr.route("VFX: Niagara sparks", profiles=[{"id": "developer", "favorite_models": []}])
    assert (got["kind"], got["profile_id"]) == ("vfx", "developer")
    assert got["model"] == sr.job_kind("vfx").model


def test_profile_own_model_beats_the_suggestion():
    profiles = [{"id": "tester", "favorite_models": ["codex:gpt-6-luna"]}]
    assert sr.route("QA: test it", profiles=profiles)["model"] == "codex:gpt-6-luna"


@pytest.fixture
def backends(monkeypatch):
    monkeypatch.setattr(fm, "known_backends", lambda: frozenset({"anthropic", "claude_code"}))
    monkeypatch.setattr(fm, "coding_agent_backends", lambda: frozenset({"claude_code"}))
    monkeypatch.setattr(fm, "billing_kind", lambda agent, provider, model="": "api_key")
    monkeypatch.setattr(fm, "_available_agent_models", lambda settings, backend="": {})


def _settings(**picks):
    return SimpleNamespace(swarm_job_models=picks, agent_api_keys=[])


def test_job_model_set_kind(backends):
    s = _settings(modeling="claude_code:claude-opus-5-5")
    assert sr.job_model("modeling", {"favorite_models": []}, s) == "claude_code:claude-opus-5-5"
    got = sr.route("Modeling: castle mesh", settings=s)
    assert got["model"] == "claude_code:claude-opus-5-5"


def test_job_model_bare_id_on_a_subscription(backends, monkeypatch):
    sel = fm.FavoriteSelection(backend="claude_code", model_id="claude-sonnet-5-5")
    monkeypatch.setattr(fm, "resolve_model_strict", lambda favs, settings: fm.ResolveOk(
        coding_agent="claude_code", model="claude-sonnet-5-5", provider="", selection=sel))
    s = _settings(research="claude-sonnet-5-5")
    assert sr.job_model("research", {"favorite_models": []}, s) == "claude-sonnet-5-5"


def test_job_model_unset_kind_is_empty(backends):
    assert sr.job_model("research", {"favorite_models": []}, _settings()) == ""


def test_job_model_unset_kind_uses_profile_model(backends):
    profile = {"favorite_models": ["claude_code:claude-opus-5-5"]}
    assert sr.job_model("research", profile, _settings()) == "claude_code:claude-opus-5-5"


def test_job_model_refuses_paid_api_model(backends):
    s = _settings(research="anthropic:claude-sonnet-5-5")
    assert sr.job_model("research", {"favorite_models": []}, s) == ""


def test_job_model_allows_paid_api_the_person_opened(backends):
    s = SimpleNamespace(swarm_job_models={"research": "anthropic:claude-sonnet-5-5"}, agent_api_keys=["anthropic"])
    assert sr.job_model("research", {}, s) == "anthropic:claude-sonnet-5-5"


def test_settings_normalizes_swarm_job_models():
    from frontend.settings import PanelSettings

    s = PanelSettings(swarm_job_models={" Modeling ": " codex:gpt-6-luna ", "bad": 3, "empty": " "})
    s.validate()
    assert s.swarm_job_models == {"modeling": "codex:gpt-6-luna"}
    s = PanelSettings(swarm_job_models=None)  # type: ignore[arg-type]
    s.validate()
    assert s.swarm_job_models == {}
    assert PanelSettings().to_json_dict()["swarm_job_models"] == {}


def test_developer_profile_is_bundled(monkeypatch):
    monkeypatch.setattr(agent_profiles, "_load_rows", lambda: [])
    ids = {p["id"] for p in agent_profiles.list_agent_profiles()}
    assert "developer" in ids
    dev = next(p for p in agent_profiles.list_agent_profiles() if p["id"] == "developer")
    assert dev["name"] == "Developer" and dev["disabled_packs"] == [] and dev["favorite_models"] == []
