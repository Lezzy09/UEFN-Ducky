"""Are Fortnite's servers up? Epic's public status page, for workflows that need a live
play session (a daily test at 8 AM waits out update downtime instead of failing)."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Callable

STATUS_URL = "https://status.epicgames.com/api/v2/summary.json"
# What a UEFN play session needs from Fortnite (an Item Shop outage doesn't stop a test).
NEEDED = ("Login", "Game Services", "Matchmaking")
_DOWN = {"major_outage", "partial_outage", "under_maintenance"}
_LIVE_MAINTENANCE = {"in_progress", "verifying"}
WAIT_CAP_MIN = 240.0


def fetch_summary(timeout: float = 15.0) -> dict[str, Any]:
    req = urllib.request.Request(STATUS_URL, headers={"User-Agent": "UEFN-Ducky", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def fortnite_status(summary: dict[str, Any]) -> dict[str, Any]:
    """``{"up", "status", "down"}`` from the status page: down lists what is out."""
    comps = [c for c in summary.get("components") or [] if isinstance(c, dict)]
    group = next((c for c in comps if c.get("group") and str(c.get("name") or "").lower() == "fortnite"), None)
    gid = str((group or {}).get("id") or "")
    parts = {str(c.get("name") or ""): str(c.get("status") or "") for c in comps if gid and str(c.get("group_id") or "") == gid}
    down = [f"{name}: {parts[name].replace('_', ' ')}" for name in NEEDED if parts.get(name) in _DOWN]
    for row in summary.get("scheduled_maintenances") or []:
        if not isinstance(row, dict) or str(row.get("status") or "") not in _LIVE_MAINTENANCE:
            continue
        hit = [c for c in row.get("components") or [] if isinstance(c, dict) and (str(c.get("id") or "") == gid or str(c.get("group_id") or "") == gid)]
        if hit:
            down.append(f"Maintenance: {row.get('name') or 'Fortnite maintenance'}")
    if not gid:
        down.append("Fortnite isn't on the status page")
    slow = [name for name in NEEDED if parts.get(name) == "degraded_performance"]
    if down:
        status = "Down — " + "; ".join(down)
    elif slow:
        status = "Up (slow: " + ", ".join(slow) + ")"
    else:
        status = "Up"
    return {"up": not down, "status": status, "down": down}


def wait_for_servers(
    cfg: dict[str, Any],
    *,
    fetch: Callable[[], dict[str, Any]] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Check now; while down, check again every ``every_seconds`` for up to ``wait_minutes``.
    True wire: up. False wire: still down when the wait ran out (or Stop was pressed)."""
    try:
        wait_min = min(max(float(cfg.get("wait_minutes") if cfg.get("wait_minutes") not in (None, "") else 60), 0.0), WAIT_CAP_MIN)
        every = max(float(cfg.get("every_seconds") or 60), 15.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Wait and Check every must be numbers.") from exc
    get = fetch or fetch_summary
    deadline = clock() + wait_min * 60
    checks = 0
    while True:
        checks += 1
        try:
            found = fortnite_status(get())
        except Exception as exc:  # offline, page down: not up yet, try again
            found = {"up": False, "status": f"Couldn't reach the Epic status page ({exc})", "down": ["status page unreachable"]}
        if found["up"] or cancelled() or clock() >= deadline:
            break
        end = min(clock() + every, deadline)
        while clock() < end and not cancelled():
            sleep(min(1.0, max(end - clock(), 0.0)))
    up = bool(found["up"])
    outputs = {"up": up, "status": found["status"]}
    return {
        "ok": True,
        "branch": up,
        "outputs": outputs,
        "result": {"servers_up": up, "servers_status": found["status"], "checks": checks},
    }
