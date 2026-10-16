"""Section reads, the search line and pack blurbs in the skill index."""

from __future__ import annotations

from pathlib import Path

from backend.skills import store


def _pack() -> Path:
    root = store.appdata_skill_packs_dir() / "sky"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: sky\ndescription: \"Sky: starfield and night sky materials for islands, with the hard rules\"\n"
        "metadata:\n  label: Sky\n---\n\n# Sky\n\n## Basics\nRead the recipe.\n",
        encoding="utf-8")
    (root / "references" / "starfield.md").write_text(
        "---\ndescription: Starfield recipe\nmetadata:\n  label: Starfield\n---\n\n"
        "## Night sky\nTwinkling stars.\n\n## Flags (HARD)\nTwo sided.\n```\n## not a heading\n```\n",
        encoding="utf-8")
    store.invalidate_skills_revision()
    return root


def test_section_read_returns_only_that_heading() -> None:
    _pack()
    text = store.skill_read_subskill("sky", "starfield", section="night sky")
    assert text.startswith("## Sky — Starfield > Night sky")
    assert "Twinkling stars." in text and "Two sided." not in text
    flags = store.skill_read_subskill("sky", "starfield", section="Flags")  # partial name matches
    assert "## not a heading" in flags


def test_unknown_section_lists_the_headings() -> None:
    _pack()
    text = store.skill_read_subskill("sky", "starfield", section="Nope")
    assert text.startswith("ERROR: no section 'Nope'")
    assert "- Night sky" in text and "- Flags (HARD)" in text


def test_prompt_index_mentions_skill_search_and_pack_blurbs() -> None:
    _pack()
    full = store.build_skill_prompt(store.SkillSelection())
    compact = store.build_skill_prompt_compact(store.SkillSelection())
    assert 'skill_search("' in full and "skill_search(" in compact
    assert "`sky` [yours] — Sky: starfield and night sky materials" in full
    line = next(line for line in compact.splitlines() if line.startswith("- `sky`"))
    assert len(line) < 110 and line.endswith("…")


def test_blurb_handles_empty_label_prefix_and_block_scalars() -> None:
    assert store._label_with_blurb("Sky", {"description": ""}, 50) == "Sky"
    assert store._label_with_blurb("Sky", {"description": ">-"}, 50) == "Sky"
    assert store._label_with_blurb("Sky", {"description": "Sky — night looks"}, 50) == "Sky: night looks"
