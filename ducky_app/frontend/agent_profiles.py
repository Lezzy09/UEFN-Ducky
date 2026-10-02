"""Bundled and user agent profiles (ducky templates)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from frontend.settings import PanelSettings

_BUNDLED_JSON = Path(__file__).resolve().parent / "bundled_agent_profiles.json"
BLANK_PROFILE_ID = "__blank__"
PROFILE_FIELDS = (
    "name",
    "ducky_style",
    "ducky_personality",
    "when_to_use",
    "disabled_packs",
    "enabled_subskills",
    "disabled_tool_ids",
    "favorite_models",
    "tts_voice",
    "tts_speed",
)


def _load_bundled_raw() -> list[dict[str, Any]]:
    if not _BUNDLED_JSON.is_file():
        return []
    try:
        data = json.loads(_BUNDLED_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, list):
        return []
    out: list[dict[str, Any]] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if not pid:
            continue
        out.append(_normalize_profile({**item, "id": pid, "kind": "bundled"}, bundled=True))
    return out


def bundled_profile_ids() -> frozenset[str]:
    return frozenset(p["id"] for p in _load_bundled_raw())


def _dedup_preserve_order(values: list[str]) -> list[str]:
    """Order-preserving de-dup for id lists (packs, tools, models).

    A repeated id is never meaningful — duplicates only bloat stored profiles
    (e.g. disabled_packs accumulating "verse" 8x) and mislead the profile editor.
    Keep the first occurrence.
    """
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_profile(raw: dict[str, Any], *, bundled: bool = False) -> dict[str, Any]:
    pid = str(raw.get("id") or "").strip()
    # Prefer deny-lists. Legacy allowlists (enabled_packs / tool_ids) are dropped —
    # empty deny = everything available (lazy-loaded).
    disabled_packs = raw.get("disabled_packs")
    disabled_tools = raw.get("disabled_tool_ids")
    favorites = raw.get("favorite_models")
    enabled_subs_raw = raw.get("enabled_subskills")
    enabled_subskills: dict[str, list[str]] = {}
    if isinstance(enabled_subs_raw, dict):
        for pack_id, ids in enabled_subs_raw.items():
            key = str(pack_id or "").strip()
            if not key or not isinstance(ids, list):
                continue
            enabled_subskills[key] = _dedup_preserve_order([str(x) for x in ids if str(x).strip()])
    return {
        "id": pid,
        "name": str(raw.get("name") or pid or "Untitled").strip() or "Untitled",
        "ducky_style": str(raw.get("ducky_style") or "artist").strip() or "artist",
        "ducky_personality": str(raw.get("ducky_personality") or "").strip(),
        "when_to_use": str(raw.get("when_to_use") or "").strip(),
        "tts_voice": str(raw.get("tts_voice") or "").strip(),
        "tts_speed": float(raw.get("tts_speed") or 0.0),
        "disabled_packs": (
            _dedup_preserve_order([str(x) for x in disabled_packs])
            if isinstance(disabled_packs, list)
            else []
        ),
        "enabled_subskills": enabled_subskills,
        "disabled_tool_ids": (
            _dedup_preserve_order([str(x) for x in disabled_tools])
            if isinstance(disabled_tools, list)
            else []
        ),
        # Single optional model override ("backend:model_id"). Legacy 2nd/3rd
        # slots are dropped on load; empty means the global default applies.
        "favorite_models": _dedup_preserve_order([str(x).strip() for x in favorites if str(x).strip()])[:1]
        if isinstance(favorites, list)
        else [],
        "kind": "bundled" if bundled else str(raw.get("kind") or "custom"),
    }


def _patch_profile(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in PROFILE_FIELDS:
        if key in patch and patch[key] is not None:
            merged[key] = patch[key]
    merged["id"] = base["id"]
    merged["kind"] = base.get("kind", "bundled")
    return _normalize_profile(merged, bundled=merged.get("kind") == "bundled")


# --------------------------------------------------------------------------- storage
# Duckies live in their own table (backend.store.repos.duckies, migration 0014), not in
# settings. Shipped duckies are always listed unless the user archived one, and nothing
# deletes a row. In settings, a hide list could hide every shipped ducky at once and any
# settings save holding an empty list wiped the custom ones.

_StoreUnavailable = (OSError, RuntimeError)


def _repo():
    from backend.store.importers import duckies as importer
    from backend.store.repos import duckies as repo

    importer.ensure()
    return repo


def _load_rows() -> list[dict[str, Any]]:
    try:
        return _repo().list_all()
    except _StoreUnavailable:
        # Database can't open: read the old settings copy so the library is never empty.
        from backend.store.importers.duckies import rows_from_settings

        s = PanelSettings.load()
        return rows_from_settings(
            {
                "agent_profiles": s.agent_profiles,
                "agent_profile_overrides": s.agent_profile_overrides,
                "archived_agent_profile_ids": s.archived_agent_profile_ids,
            },
            now=0.0,
        )


def _library() -> list[tuple[dict[str, Any], bool]]:
    """(profile, archived) for every shipped ducky, then custom duckies in the order made."""
    rows = _load_rows()
    by_id = {r["id"]: r for r in rows}
    out: list[tuple[dict[str, Any], bool]] = []
    bundled = _load_bundled_raw()
    for template in bundled:
        row = by_id.get(template["id"])
        edits = row["data"] if row and row["kind"] == "bundled" else {}
        out.append((_patch_profile(template, edits) if edits else template, bool(row and row["archived"])))
    shipped = {t["id"] for t in bundled}
    for row in rows:
        if row["kind"] == "custom" and row["id"] not in shipped:
            out.append((_normalize_profile({**row["data"], "id": row["id"]}, bundled=False), bool(row["archived"])))
    return out


def list_bundled_agent_profile_templates() -> list[dict[str, Any]]:
    return list(_load_bundled_raw())


def list_agent_profiles() -> list[dict[str, Any]]:
    """Duckies shown in the library: every one not in Archive."""
    return [p for p, archived in _library() if not archived]


def list_archived_agent_profiles() -> list[dict[str, Any]]:
    return [p for p, archived in _library() if archived]


def list_agent_profiles_available() -> list[dict[str, Any]]:
    """All shipped + custom duckies (Archive included) for spawn, delegation, and template pickers."""
    return [p for p, _archived in _library()]


def get_agent_profile(profile_id: str) -> dict[str, Any] | None:
    pid = str(profile_id or "").strip()
    if not pid or pid == BLANK_PROFILE_ID:
        return None
    for profile in list_agent_profiles_available():
        if profile.get("id") == pid:
            return profile
    return None


def _dedupe_profile_name(base_name: str) -> str:
    """Avoid collisions with existing profile names ("X Copy", "X Copy 2", …)."""
    existing = {str(p.get("name") or "").strip().lower() for p in list_agent_profiles()}
    candidate = base_name.strip() or "Untitled"
    if candidate.lower() not in existing:
        return candidate
    n = 2
    while f"{candidate} {n}".lower() in existing:
        n += 1
    return f"{candidate} {n}"


def duplicate_agent_profile(profile_id: str) -> dict[str, Any]:
    """Clone any bundled or custom profile (with overrides applied) into a new custom profile."""
    source = get_agent_profile(profile_id)
    if not source:
        raise ValueError(f"Profile not found: {profile_id}")
    raw = {key: source.get(key) for key in PROFILE_FIELDS}
    raw["name"] = _dedupe_profile_name(f"{source.get('name') or 'Untitled'} Copy")
    raw["id"] = str(uuid.uuid4())
    raw["kind"] = "custom"
    return save_agent_profile(raw)


def save_agent_profile(profile: dict[str, Any]) -> dict[str, Any]:
    raw = _normalize_profile(profile, bundled=False)
    pid = str(raw.get("id") or "").strip()
    if pid in bundled_profile_ids():
        raise ValueError("Bundled profiles cannot be saved as custom — use save_agent_profile_override")
    if not pid:
        pid = str(uuid.uuid4())
        raw["id"] = pid
    raw["kind"] = "custom"
    _repo().save(pid, "custom", raw)
    return raw


def save_agent_profile_override(bundled_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    bid = str(bundled_id or "").strip()
    bundled = next((p for p in _load_bundled_raw() if p["id"] == bid), None)
    if not bundled:
        raise ValueError(f"Not a bundled profile: {bundled_id}")
    repo = _repo()
    row = repo.get(bid)
    existing = row["data"] if row and row["kind"] == "bundled" else {}
    merged_patch = {**existing, **{k: v for k, v in patch.items() if k in PROFILE_FIELDS}}
    # De-dup list fields before storing so a bloated edit heals itself on the next save.
    for _key in ("enabled_packs", "tool_ids", "favorite_models"):
        if isinstance(merged_patch.get(_key), list):
            merged_patch[_key] = _dedup_preserve_order([str(x) for x in merged_patch[_key]])
    repo.save(bid, "bundled", merged_patch)
    return _patch_profile(bundled, merged_patch)


def _kind(profile_id: str) -> str:
    return "bundled" if profile_id in bundled_profile_ids() else "custom"


def archive_agent_profile(profile_id: str) -> dict[str, Any]:
    """Move a library profile into Archive. Existing chats stay where they are."""
    pid = str(profile_id or "").strip()
    if not pid or pid == BLANK_PROFILE_ID:
        raise ValueError("profile_id is required")
    for profile, archived in _library():
        if profile["id"] == pid:
            if not archived:
                _repo().set_archived(pid, _kind(pid), True)
            return profile
    raise ValueError(f"Profile not found: {profile_id}")


def unarchive_agent_profile(profile_id: str) -> dict[str, Any]:
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id is required")
    if pid not in {p["id"] for p in list_archived_agent_profiles()}:
        raise ValueError(f"Profile is not archived: {profile_id}")
    _repo().set_archived(pid, _kind(pid), False)
    profile = get_agent_profile(pid)
    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")
    return profile


def delete_agent_profile(profile_id: str) -> None:
    """Shipped duckies go to Archive (restorable); custom ones are marked deleted, row kept."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id is required")
    if pid in bundled_profile_ids():
        archive_agent_profile(pid)
        return
    if not _repo().set_deleted(pid, True):
        raise ValueError(f"Profile not found: {profile_id}")
