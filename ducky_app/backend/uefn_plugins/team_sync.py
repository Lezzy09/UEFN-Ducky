"""Team data sync (plan §7, P3 docs + P4 assets): one batched Store call per team.

A round pushes the scope's queued changes (≤100), uploads accepted bytes to the
presigned PUT URLs, commits them, and pulls everything since the cursor from
presigned GET URLs (sha256 checked). Last write wins in server order: a stale
push adopts the server's copy.

Load (the 2026-09-16 outage was a desktop poller holding every plugin slot): a
round runs only while a team-scoped plugin panel is open (the host scope bar asks
on open, on focus and each minute), at most once a minute per team, and never
per document. Offline writes stay queued (``dirty``) for the next round.
"""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from backend.store.repos import plugin_data as repo
from backend.uefn_plugins import scopes

MIN_INTERVAL_S = 60.0
MAX_PUSHES = 100
# ponytail: pages per round are capped so one round stays bounded; the next round
# continues from the saved cursor.
MAX_PAGES = 20
TRANSFER_TIMEOUT_S = 300.0

_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class SyncError(Exception):
    def __init__(self, message: str, *, offline: bool = False) -> None:
        super().__init__(message)
        self.offline = offline


# --------------------------------------------------------------------------- transport


class Transport:
    """Store collect calls as the signed-in account + presigned URL transfers.
    Tests pass a fake with the same three methods."""

    def collect(self, event: str, body: dict[str, Any]) -> dict[str, Any]:
        from frontend.duckyos_account import DuckyOSAccountError, api_request

        try:
            status, parsed, _raw = api_request(
                "POST", f"/api/v1/plugins/uefn-ducky-store/collect/{event}", body, timeout=60.0
            )
        except DuckyOSAccountError as exc:
            raise SyncError(exc.message, offline=True) from exc
        payload = parsed.get("payload") if isinstance(parsed, dict) else None
        payload = payload if isinstance(payload, dict) else (parsed or {})
        if 200 <= int(status) < 300:
            return payload
        err = str(payload.get("error") or (parsed or {}).get("error") or f"HTTP {status}")
        raise SyncError(err, offline=int(status) >= 500)

    def put(self, url: str, data: bytes) -> None:
        req = urllib.request.Request(
            url, data=data, method="PUT", headers={"Content-Length": str(len(data))}
        )
        try:
            with urllib.request.urlopen(req, timeout=TRANSFER_TIMEOUT_S) as resp:
                resp.read()
        except (OSError, urllib.error.URLError) as exc:
            raise SyncError(f"upload failed: {exc}", offline=True) from exc

    def get(self, url: str) -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=TRANSFER_TIMEOUT_S) as resp:
                return resp.read()
        except (OSError, urllib.error.URLError) as exc:
            raise SyncError(f"download failed: {exc}", offline=True) from exc


# --------------------------------------------------------------------------- one round


def _item(d: dict[str, Any]) -> tuple[str, str, str] | None:
    kind, pid, key = str(d.get("kind") or "doc"), str(d.get("pluginId") or ""), str(d.get("key") or "")
    ok = scopes.valid_plugin_id(pid) and (
        (kind == "doc" and scopes.valid_doc_key(key)) or (kind == "asset" and scopes.valid_asset_path(key))
    )
    return (kind, pid, key) if ok else None


def _local_bytes(scope: dict[str, Any], row: dict[str, Any]) -> bytes | None:
    if row["kind"] == "doc":
        return None if row["value"] is None else row["value"].encode("utf-8")
    path = scopes.asset_file(scope, row["plugin_id"], row["key"])
    return path.read_bytes() if path.is_file() else None


def _drop_local(scope: dict[str, Any], kind: str, pid: str, key: str) -> None:
    repo.remove(scope["account"], scope["id"], pid, kind, key, tombstone=False)
    if kind == "asset":
        scopes.asset_file(scope, pid, key).unlink(missing_ok=True)


def _store(scope: dict[str, Any], kind: str, pid: str, key: str, data: bytes, rev: int) -> None:
    sha = hashlib.sha256(data).hexdigest()
    if kind == "asset":
        scopes.write_asset_bytes(scopes.asset_file(scope, pid, key), data)
        repo.put(scope["account"], scope["id"], pid, kind, key, value=None, size=len(data), sha256=sha,
                 dirty=False, rev=rev)
    else:
        repo.put(scope["account"], scope["id"], pid, kind, key, value=data.decode("utf-8"), size=len(data),
                 sha256=sha, dirty=False, rev=rev)


def _download(t: Transport, item: dict[str, Any]) -> bytes:
    data = t.get(str(item.get("getUrl") or ""))
    if hashlib.sha256(data).hexdigest() != str(item.get("sha256") or ""):
        raise SyncError("downloaded file failed its sha256 check")
    return data


def _apply_change(scope: dict[str, Any], t: Transport, ch: dict[str, Any], changed: set[str]) -> None:
    it = _item(ch)
    if it is None:
        return
    kind, pid, key = it
    rev = int(ch.get("rev") or 0)
    local = repo.get(scope["account"], scope["id"], pid, kind, key)
    # The cursor is inclusive: rows we already hold at this rev come back; skip them.
    if local and (local["dirty"] or (local["rev"] == rev and not local["deleted"])):
        return  # a queued local change is settled by its push (stale → adopt)
    if ch.get("deleted"):
        if local:
            _drop_local(scope, kind, pid, key)
            changed.add(pid)
        return
    if not ch.get("getUrl"):
        return
    _store(scope, kind, pid, key, _download(t, ch), rev)
    changed.add(pid)


def _adopt(scope: dict[str, Any], t: Transport, it: tuple[str, str, str], server: Any, changed: set[str]) -> int | None:
    """Stale push: the server's copy wins. Returns a rev to rewind the cursor to when
    the server row came without content (the next inclusive pull brings it)."""
    kind, pid, key = it
    if not isinstance(server, dict) or not server:
        # The server has no such item any more: push it again as new.
        repo.set_rev(scope["account"], scope["id"], pid, kind, key, 0)
        return None
    changed.add(pid)
    if server.get("deleted"):
        _drop_local(scope, kind, pid, key)
        return None
    if server.get("getUrl"):
        _store(scope, kind, pid, key, _download(t, server), int(server.get("rev") or 0))
        return None
    _drop_local(scope, kind, pid, key)
    return int(server.get("rev") or 0)


def _lock(account: str, team: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((account, team), threading.Lock())


def sync_team(account: str, team: str, *, force: bool = False, transport: Transport | None = None,
              now: Callable[[], float] = time.time) -> dict[str, Any]:
    """One sync round for ``(account, team)``. Returns ``{state, changed, error}``."""
    if not scopes.valid_team_id(team):
        return {"state": "unavailable", "changed": [], "error": "invalid team"}
    lock = _lock(account, team)
    if not lock.acquire(blocking=False):
        return {"state": "busy", "changed": [], "error": ""}
    try:
        st = repo.sync_get(account, team)
        if not force and now() - float(st["called_at"]) < MIN_INTERVAL_S:
            return {"state": st["state"], "changed": [], "error": st["error"], "skipped": True}
        repo.sync_put(account, team, called_at=now())
        return _round(account, team, int(st["cursor_rev"]), transport or Transport(), now)
    finally:
        lock.release()


FIRST_PULL_WAIT_S = 10.0
_FIRST_PULL_TRIED: set[tuple[str, str]] = set()


def first_pull(account: str, team: str, *, timeout: float = FIRST_PULL_WAIT_S) -> bool:
    """Pull a team scope this PC never pulled before the plugin gets its data API.

    Waits at most ``timeout`` seconds, once per scope per process: a plugin that
    seeds defaults when empty must never push them over the team's data. Offline or
    slow, the scope stays read-only ("waiting") and the round finishes in the
    background; the scope bar's minute sync keeps retrying. Returns whether the
    scope has been pulled now.
    """
    key = (account, team)
    if key in _FIRST_PULL_TRIED or not scopes.valid_team_id(team):
        return False
    _FIRST_PULL_TRIED.add(key)
    done = threading.Event()

    def _work() -> None:
        try:
            with _lock(account, team):  # a round already running for this scope finishes first
                st = repo.sync_get(account, team)
                if st["synced_at"]:
                    return
                repo.sync_put(account, team, called_at=time.time())
                out = _round(account, team, int(st["cursor_rev"]), Transport(), time.time)
            try:
                from frontend.ui_web.agent_modes import push_ui_event

                push_ui_event({"type": "plugin_scope_changed", "plugins": out.get("changed") or [], "synced": True})
            except Exception:
                pass
        finally:
            done.set()

    threading.Thread(target=_work, name="team-data-first-pull", daemon=True).start()
    done.wait(timeout)
    return bool(repo.sync_get(account, team)["synced_at"])


def _round(account: str, team: str, cursor: int, t: Transport, now: Callable[[], float]) -> dict[str, Any]:
    scope = {"account": account, "id": team, "kind": "team"}
    changed: set[str] = set()
    errors: list[str] = []
    pushes: list[dict[str, Any]] = []
    # Pushes carry metadata only; bytes are read one item at a time at upload.
    sent: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in repo.dirty(account, team, MAX_PUSHES):
        it = (row["kind"], row["plugin_id"], row["key"])
        push = {"kind": it[0], "pluginId": it[1], "key": it[2], "baseRev": int(row["rev"])}
        if row["deleted"]:
            push.update(size=0, sha256="", delete=True)
        else:
            push.update(size=int(row["size"]), sha256=row["sha256"])
            sent[it] = row
        pushes.append(push)
    try:
        resp = t.collect("team-data-sync", {"teamId": team, "cursorRev": cursor, "pushes": pushes})
        commits = []
        for a in resp.get("accepted") or []:
            it = _item(a)
            if it is None or it not in sent:
                continue
            data = _local_bytes(scope, sent[it])
            if data is None or hashlib.sha256(data).hexdigest() != sent[it]["sha256"]:
                continue  # changed or gone since: its upload expires, the next round pushes the new copy
            t.put(str(a.get("putUrl") or ""), data)
            commits.append({"kind": it[0], "pluginId": it[1], "key": it[2], "rev": int(a.get("rev") or 0)})
        for d in resp.get("deleted") or []:
            it = _item(d)
            if it:
                repo.mark_pushed(account, team, it[1], it[0], it[2], rev=int(d.get("rev") or 0), sha256="")
        rewind: list[int] = []
        for s in resp.get("stale") or []:
            it = _item(s)
            if it:
                back = _adopt(scope, t, it, s.get("server"), changed)
                if back is not None:
                    rewind.append(back)
        for r in resp.get("refused") or []:
            it = _item(r)
            if it:
                # Not shared (too big, storage full): the local copy stays, the bar says why.
                repo.clear_dirty(account, team, it[1], it[0], it[2])
                errors.append(f"{it[2]}: {r.get('error') or 'refused'}")
        usage = resp.get("usage") or {}
        pages = 0
        while True:
            for ch in resp.get("changes") or []:
                _apply_change(scope, t, ch, changed)
            cursor = int(resp.get("cursorRev") or cursor)
            pages += 1
            if not resp.get("more") or pages >= MAX_PAGES:
                break
            resp = t.collect("team-data-sync", {"teamId": team, "cursorRev": cursor})
            usage = resp.get("usage") or usage
        if commits:
            res = t.collect("team-data-commit", {"teamId": team, "commits": commits})
            usage = res.get("usage") or usage
            for r in res.get("results") or []:
                it = _item(r)
                if it is None:
                    continue
                status = r.get("status")
                if status in ("committed", "unchanged"):
                    repo.mark_pushed(account, team, it[1], it[0], it[2], rev=int(r.get("rev") or 0),
                                     sha256=str((sent.get(it) or {}).get("sha256") or ""))
                elif status == "stale":
                    back = _adopt(scope, t, it, r.get("server"), changed)
                    if back is not None:
                        rewind.append(back)
                else:
                    errors.append(f"{it[2]}: upload not accepted, retrying")
        if rewind:
            cursor = min([cursor, *rewind])
    except SyncError as exc:
        return _failed(account, team, exc, changed)
    repo.sync_put(account, team, cursor_rev=cursor, state="ok", error="; ".join(errors)[:500], usage=usage,
                  synced_at=now())
    return {"state": "ok", "changed": sorted(changed), "error": "; ".join(errors)}


def _failed(account: str, team: str, exc: SyncError, changed: set[str]) -> dict[str, Any]:
    msg = str(exc)
    low = msg.lower()
    if "team not found" in low:
        # Removed from the team (or it is gone): its local copy goes too (plan §7).
        scopes.purge_team(account, team)
        return {"state": "removed", "changed": sorted(changed), "error": ""}
    if low.startswith("plan_paused"):
        state = "paused"
    elif "storage isn't available" in low or low.startswith("permission denied"):
        state = "unavailable"  # Personal only, silently
    else:
        state = "offline" if exc.offline else "error"
    repo.sync_put(account, team, state=state, error=msg[:500])
    return {"state": state, "changed": sorted(changed), "error": msg}


# --------------------------------------------------------------------------- host glue


def sync_active(*, force: bool = False, on_done: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Start a round for the active team scope on a worker thread (no-op for Personal)."""
    scope = scopes.active_scope()
    if scope["kind"] != "team":
        return {"ok": True, "started": False}

    def _work() -> None:
        out = sync_team(scope["account"], scope["id"], force=force)
        if on_done and (out.get("changed") or not out.get("skipped")):
            on_done(out)

    threading.Thread(target=_work, name="team-data-sync", daemon=True).start()
    return {"ok": True, "started": True}


def scope_status() -> dict[str, Any]:
    """What the host scope bar shows. ``visible`` is false for accounts without the
    Teams beta (rule 13: normal members see no change)."""
    from frontend.duckyos_account import get_status

    scope = scopes.active_scope()
    account = scope["account"]
    out: dict[str, Any] = {
        "ok": True,
        "visible": scope["kind"] == "team" or teams_enabled(),
        "scope": scopes.scope_view(scope),
        "email": str(get_status().get("email") or ""),
        "canChange": account != scopes.LOCAL and bool(scopes.current_project()),
    }
    if scope["kind"] == "team":
        st = repo.sync_get(account, scope["id"])
        out.update(
            members=int(st["members"]),
            state=scope["state"],
            error=st["error"],
            syncedAt=float(st["synced_at"]) or None,
            pending=repo.count_dirty(account, scope["id"]),
            usage=st["usage"] or {},
        )
    return out


def teams_enabled() -> bool:
    """The account has the Teams beta: the last Store catalog fetched as this account said so."""
    from backend.store.repos import kv
    from frontend.duckyos_account import account_key

    key = account_key()
    doc = kv.get_doc("cache_docs", "store_catalog")
    cat = doc.get("catalog") if isinstance(doc, dict) else None
    return bool(key) and isinstance(cat, dict) and cat.get("account") == key and cat.get("teams") is True


def scope_choices() -> dict[str, Any]:
    """Personal + the account's teams with Team Private active. Calls the Store hub
    (which also claims pending invites), so only on Change ▾ open, never on a timer."""
    from frontend.duckyos_account import teams_snapshot

    account = scopes.account_id()
    choices = [{"id": scopes.PERSONAL, "kind": "personal", "label": "Personal"}]
    if account == scopes.LOCAL or not teams_enabled():
        return {"ok": True, "choices": choices}
    try:
        snap = teams_snapshot()
    except Exception:
        snap = {}
    for team in snap.get("teams") or []:
        plan = team.get("private_plan") or {}
        team_id = str(team.get("id") or "")
        if plan.get("status") not in ("active", "comped") or not scopes.valid_team_id(team_id):
            continue
        members = len(team.get("members") or [])
        label = str(team.get("name") or "Team")
        repo.sync_put(account, team_id, label=label, members=members)
        choices.append({"id": team_id, "kind": "team", "label": label, "members": members})
    return {"ok": True, "choices": choices}


def link_scope(scope_id: str) -> dict[str, Any]:
    """Change ▾: point the open project at Personal or a team (the web confirmed first)."""
    scopes.link_project(scope_id)
    return scope_status()
