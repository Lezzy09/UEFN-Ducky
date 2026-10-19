"""What's new after an update: the short changes of the versions this PC hasn't seen yet."""

from __future__ import annotations

from typing import Any

from frontend import __version__
from frontend.version_check import is_remote_newer

# Last app version whose What's new was shown (or skipped) here, in ducky.db `meta`.
META_LAST_SEEN = "whats_new.last_seen"
# The window lists at most this many versions, newest first.
MAX_VERSIONS = 5


def _meta_get(key: str) -> str | None:
    try:
        from backend.store.repos.kv import meta_get

        return meta_get(key)
    except Exception:
        return None


def _meta_set(key: str, value: str) -> None:
    try:
        from backend.store.repos.kv import meta_set

        meta_set(key, value)
    except Exception:
        pass


def _fresh_install() -> bool:
    """True before a fresh install's first setup finished (no What's new for a first start)."""
    try:
        from frontend.starter_llm_gateways import starter_llm_onboard_pending

        return bool(starter_llm_onboard_pending().get("pending"))
    except Exception:
        return False


def _enabled() -> bool:
    try:
        from frontend.settings import PanelSettings

        return bool(getattr(PanelSettings.load(), "whats_new_popup", True))
    except Exception:
        return True


def _items(row: dict[str, Any]) -> list[dict[str, str]]:
    items = row.get("items")
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append({"kind": str(item.get("kind") or "improved"), "text": str(item["text"]).strip()})
    return out


def _with_items(rows: list[dict[str, Any]], current: str) -> list[dict[str, Any]]:
    """Versions up to ``current`` that have short changes, newest first."""
    picked = []
    for row in rows:
        ver = str(row.get("version") or "").strip()
        items = _items(row)
        if not ver or not items or is_remote_newer(current, ver):
            continue
        if any(p["version"] == ver for p in picked):
            continue
        picked.append({"version": ver, "created_at": row.get("created_at"), "items": items})
    picked.sort(key=lambda r: _sort_key(r["version"]), reverse=True)
    return picked


def _sort_key(version: str) -> tuple[int, int, int]:
    from frontend.version_check import parse_version_tuple

    return parse_version_tuple(version) or (0, 0, 0)


def whats_new(
    rows: list[dict[str, Any]],
    *,
    current: str,
    last_seen: str | None,
    fresh_install: bool,
    enabled: bool,
) -> dict[str, Any]:
    """Decide what the window shows. ``mark`` is the version to save as seen without
    showing anything (a fresh install, or a running version with no short changes)."""
    known = {str(r.get("version") or "").strip() for r in rows}
    released = next((r for r in rows if str(r.get("version") or "").strip() == current), None)
    result: dict[str, Any] = {
        "current": current,
        "last_seen": last_seen,
        "released_at": released.get("created_at") if released else None,
        "enabled": enabled,
        "show": False,
        "versions": [],
        "recent": _with_items(rows, current)[:MAX_VERSIONS],
        "mark": None,
    }
    if last_seen and not is_remote_newer(last_seen, current):
        return result
    if last_seen is None and fresh_install:
        result["mark"] = current
        return result
    if current not in known:
        # Offline, or the feed doesn't list this build yet: ask again next start.
        return result
    if last_seen is None:
        unseen = [r for r in result["recent"] if r["version"] == current]
    else:
        unseen = [r for r in result["recent"] if is_remote_newer(last_seen, r["version"])]
    if not unseen:
        result["mark"] = current
        return result
    result["versions"] = unseen
    if enabled:
        result["show"] = True
    else:
        result["mark"] = current
    return result


def get_whats_new() -> dict[str, Any]:
    """The panel's start-up question: show the window, and with which versions."""
    from frontend.version_check import get_app_patch_notes

    notes = get_app_patch_notes()
    rows = [r for r in notes.get("versions") or [] if isinstance(r, dict)]
    result = whats_new(
        rows,
        current=__version__,
        last_seen=_meta_get(META_LAST_SEEN),
        fresh_install=_fresh_install(),
        enabled=_enabled(),
    )
    if result["mark"]:
        _meta_set(META_LAST_SEEN, str(result["mark"]))
    result["error"] = notes.get("error")
    return result


def mark_whats_new_seen(version: str, dont_show_again: bool = False) -> dict[str, Any]:
    """Save ``version`` as seen (never moving back), and turn the window off when asked."""
    version = str(version or "").strip() or __version__
    last = _meta_get(META_LAST_SEEN)
    if not last or is_remote_newer(last, version):
        _meta_set(META_LAST_SEEN, version)
    if dont_show_again:
        try:
            from frontend.settings import PanelSettings

            settings = PanelSettings.load()
            settings.whats_new_popup = False
            settings.save()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True}
