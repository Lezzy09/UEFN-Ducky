"""Two Duckies on one PC, end to end: team sync and Live together between them.

Drives two running apps through their loopback panel APIs (A and B, each signed in and
on the same team copy of the plugin) and prints PASS or the stage that got stuck:

    py -3 scripts/two_app_e2e.py                 # sync, then live
    py -3 scripts/two_app_e2e.py --only sync --a 4199 --b 4299

sync: A writes a doc and a small PNG, A sends them (pending 0), B pulls them (incoming 0,
same bytes) and B's History shows the change. The probe is deleted again afterwards.
live: B joins A's group; presence, hello (B's Hub got rtc commands), link path, a
``ducky.pointer`` from A reaches B's page events, a ``ducky.view`` from A reaches B
(Follow), and B's panel hears a refresh on join. B goes back to the room it was in.
imk: every team file reads back on B with the same bytes (no "Not on this PC yet"), Undo
of B's own change from History lands on both, and a control A holds (live message and
presence) and an item A locks show on B.
Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import time
import urllib.request
import zlib
from typing import Any, Callable


class App:
    def __init__(self, name: str, port: int, plugin: str) -> None:
        self.name, self.port, self.plugin = name, port, plugin
        self.cursor = 0

    def call(self, method: str, *args: Any, timeout: float = 90) -> Any:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/__panel_api/{method}",
            data=json.dumps({"args": list(args)}).encode(), headers={"Content-Type": "application/json"})
        out = json.load(urllib.request.urlopen(req, timeout=timeout))
        if not out.get("ok"):
            raise RuntimeError(f"{self.name} {method}: {out.get('error')}")
        return out.get("result")

    def data(self, op: str, **params: Any) -> dict[str, Any]:
        out = self.call("plugin_data", self.plugin, op, params)
        if not out.get("ok", True):
            raise RuntimeError(f"{self.name} {op}: {out.get('error')}")
        return out

    def status(self) -> dict[str, Any]:
        return self.call("plugin_scope_status", self.plugin)

    def live(self) -> dict[str, Any]:
        return self.call("plugin_live_status", self.plugin)

    def mark(self) -> None:
        """Events from now on (the page's own event poll keeps its own cursor)."""
        self.cursor = int(self._events(0).get("head") or 0)

    def _events(self, since: int) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.port}/__panel_events?since={since}"
        return json.load(urllib.request.urlopen(url, timeout=40))

    def events(self) -> list[dict[str, Any]]:
        body = self._events(self.cursor)
        self.cursor = int(body.get("cursor") or self.cursor)
        return [e for e in body.get("events") or [] if isinstance(e, dict)]


def wait(what: Callable[[], Any], timeout: float, every: float = 1.0) -> tuple[Any, float]:
    """``what()`` until it is truthy: (value, seconds), or (last value, -1) on timeout."""
    t0 = time.monotonic()
    value = None
    while time.monotonic() - t0 < timeout:
        value = what()
        if value:
            return value, time.monotonic() - t0
        time.sleep(every)
    return value, -1.0


def png(stamp: str) -> bytes:
    """A 2x2 PNG whose pixels carry the stamp, so every run uploads a new blob."""
    seed = zlib.crc32(stamp.encode())
    rows = b"".join(b"\x00" + bytes((seed >> s) & 255 for s in (0, 8, 16) for _ in range(2)) for _ in range(2))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def stuck(st: dict[str, Any]) -> str:
    """Why a copy isn't settled, from its status."""
    bits = [f"state {st.get('state')}"]
    if st.get("error"):
        bits.append(str(st["error"]))
    ch = st.get("changes") or {}
    bits.append(f"pending {st.get('pending')} incoming {ch.get('incoming')} head {st.get('head')}")
    for it in (st.get("items") or [])[:3]:
        bits.append(json.dumps(it)[:160])
    return " · ".join(bits)


def people(app: App) -> list[tuple[str, str, str]]:
    """Who the app's team presence lists: (PC label, device id, live room) per PC."""
    st = app.call("plugin_scope_activity", app.plugin)
    return [(str(p.get("device")), str(p.get("deviceId", ""))[:8],
             str(((p.get("plugins") or {}).get(app.plugin) or {}).get("live") or "")[:12]) for p in st.get("people") or []]


def same_team(a: App, b: App) -> str:
    sa, sb = a.status(), b.status()
    ia, ib = (sa.get("scope") or {}).get("spaceId"), (sb.get("scope") or {}).get("spaceId")
    if not ia or ia != ib:
        return f"setup: A on {ia or 'Local'}, B on {ib or 'Local'} (both need the same team copy)"
    return ""


def run_sync(a: App, b: App, timeout: float) -> bool:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    key, path, blob = f"e2e.probe.{stamp}", f"e2e/probe-{stamp}.png", png(stamp)
    value = {"probe": stamp, "from": a.name}
    try:
        a.data("data.put", key=key, value=value)
        a.data("files.put", path=path, b64=base64.b64encode(blob).decode())
    except Exception as exc:
        print(f"FAIL A write: {exc}")
        return False
    try:
        a.call("plugin_scope_push", a.plugin, f"e2e probe {stamp}")
    except Exception as exc:
        print(f"note: A push: {exc} (waiting for its auto round)")

    def sent() -> Any:
        st = a.status()
        out = (st.get("changes") or {}).get("outgoing") or []
        return st if st.get("state") == "ok" and not st.get("pending") and not out else None

    st_a, t_send = wait(sent, timeout, 1.0)
    if t_send < 0:
        print(f"FAIL A send stuck: {stuck(a.status())}")
        return False
    head = int(st_a.get("head") or 0)

    def pulled(method: str) -> Callable[[], Any]:
        def check() -> Any:
            b.call(method, b.plugin, *((True,) if method == "plugin_scope_sync" else ()))
            st = b.status()
            if int(st.get("head") or 0) < head or (st.get("changes") or {}).get("incoming"):
                return None
            got = b.data("data.get", key=key).get("value")
            f = b.data("files.get", path=path)
            return got == value and f.get("b64") and base64.b64decode(f["b64"]) == blob
        return check

    # B's own rounds first (what a teammate gets without touching anything), then Pull.
    _, t_pull = wait(pulled("plugin_scope_sync"), timeout / 2, 3.0)
    if t_pull < 0:
        st = b.status()
        print(f"note: B's auto round didn't land it in {timeout / 2:.0f} s ({stuck(st)}); trying Pull")
        _, t_pull = wait(pulled("plugin_scope_pull"), timeout / 2, 3.0)
    if t_pull < 0:
        st = b.status()
        got = b.data("data.get", key=key).get("value")
        has = bool(b.call("plugin_data", b.plugin, "files.get", {"path": path}).get("b64"))
        print(f"FAIL B incoming stuck (doc {'ok' if got == value else 'missing'}, png {'ok' if has else 'missing'}): {stuck(st)}")
        return False

    hist = b.call("plugin_scope_history", b.plugin, {"limit": 20}).get("entries") or []
    seq = next((e.get("seq") for e in hist if ["doc", key] in (e.get("items") or [])), None)
    if seq is None:
        print(f"send {t_send:.1f} s · pull {t_pull:.1f} s · FAIL history: no changeset with {key} on B")
        return False
    print(f"send {t_send:.1f} s · pull {t_pull:.1f} s · history #{seq} · PASS")
    try:  # leave the team copy as it was
        a.data("data.delete", key=key)
        a.data("files.delete", path=path)
    except Exception as exc:
        print(f"note: probe cleanup on A: {exc}")
    return True


def run_live(a: App, b: App, timeout: float) -> bool:
    ok_all = True

    def check(name: str, ok: bool, detail: str = "") -> bool:
        nonlocal ok_all
        ok_all &= ok
        print(f"{name} {'ok' if ok else 'FAIL'}{(': ' + detail) if detail else ''}")
        return ok

    la = a.live()
    if not la.get("supported"):
        return check("setup", False, f"A: {la.get('reason')}")
    a_joined = False
    if not la.get("on"):
        la = a.call("plugin_live_join", a.plugin, "")
        a_joined = True
    room = str(la.get("room") or "")
    a_dev = next((m["device"] for g in la.get("groups") or [] for m in g.get("members") or [] if m.get("me")), "")
    lb = b.live()
    b_was = str(lb.get("room") or "") if lb.get("on") else ""

    b.mark()
    try:
        b.call("plugin_live_join", b.plugin, room)
    except Exception as exc:
        check("join", False, str(exc))
        return False
    seen: list[dict[str, Any]] = []

    def drain() -> list[dict[str, Any]]:
        seen.extend(b.events())
        return seen

    try:
        def in_room() -> Any:
            st = b.live()
            return any(m.get("device") == a_dev for g in st.get("groups") or [] if g.get("room") == room
                       for m in g.get("members") or []) or None

        _, t = wait(in_room, timeout, 1.0)
        if not check("presence", t >= 0, f"A ({a_dev[:8]}) in B's room {room} after {t:.1f} s" if t >= 0
                     else f"B doesn't see A in {room}"):
            return False

        b_dev = next((m["device"] for g in b.live().get("groups") or [] for m in g.get("members") or []
                      if m.get("me")), "")

        def path(app: App, device: str) -> str:
            return next((str(p.get("path")) for p in app.live().get("peers") or [] if p.get("device") == device),
                        "absent")

        def linked() -> Any:  # both ways: a link one side reports and the other doesn't carries nothing
            drain()
            pb, pa = path(b, a_dev), path(a, b_dev)
            return (pb, pa) if pb in ("direct", "forwarded") and pa in ("direct", "forwarded") else None

        paths, t = wait(linked, timeout, 1.0)
        rtc = sum(1 for e in seen if e.get("type") == "rtc_cmd")
        check("hello", rtc > 0 or t >= 0, f"{rtc} rtc_cmd on B" if rtc else
              "link was already up" if t >= 0 else "no rtc_cmd on B: hello never arrived")
        if not check("link", t >= 0, f"B->A {paths[0]}, A->B {paths[1]} in {t:.1f} s" if t >= 0 else
                     f"B sees A {path(b, a_dev)}, A sees B ({b_dev[:8]}) {path(a, b_dev)}; B in A's roster: "
                     f"{any(m.get('device') == b_dev for g in a.live().get('groups') or [] for m in g.get('members') or [])}"
                     f"; A's team people {people(a)}"):
            return False

        probe = f"e2e-{time.time():.0f}"

        def got(topic: str) -> Any:
            drain()
            return next((e for e in seen if e.get("type") == "live_message" and e.get("plugin") == b.plugin
                         and e.get("topic") == topic and (e.get("from") or {}).get("device") == a_dev
                         and (e.get("data") or {}).get("probe") == probe), None)

        sent = a.call("plugin_live_send", a.plugin, "ducky.pointer", {"x": 0.5, "y": 0.5, "probe": probe})
        _, t = wait(lambda: got("ducky.pointer"), 10, 0.5)
        check("pointer", t >= 0, f"{t:.1f} s" if t >= 0 else f"A sent on {sent.get('sent')} link(s), B's page got nothing in 10 s")

        sent = a.call("plugin_live_send", a.plugin, "ducky.view", {"view": "e2e", "probe": probe})
        _, t = wait(lambda: got("ducky.view"), 10, 0.5)
        check("follow", t >= 0, f"ducky.view in {t:.1f} s" if t >= 0 else
              f"no ducky.view on B in 10 s (A sent on {sent.get('sent')} link(s))")

        if not ok_all:  # what B's page did get, to tell delivery from filtering
            msgs = [(e.get("topic"), (e.get("from") or {}).get("device", "")[:8]) for e in seen
                    if e.get("type") == "live_message"]
            print(f"  B live_message since join: {len(msgs)} {sorted(set(msgs))[:8]}; "
                  f"A peers {[(p.get('device', '')[:8], p.get('path')) for p in a.live().get('peers') or []]}")
        refreshed = [e for e in seen if e.get("type") in ("plugin_scope_changed", "uefn_plugins_changed")
                     and b.plugin in (e.get("plugins") or [b.plugin])]
        check("refresh on join", bool(refreshed), f"{len(refreshed)} event(s)" if refreshed else
              "no plugin_scope_changed on B after join")
        return ok_all
    finally:
        try:
            if b_was and b_was != room:
                b.call("plugin_live_join", b.plugin, b_was)
            elif not b_was:
                b.call("plugin_live_leave", b.plugin)
            if a_joined:
                a.call("plugin_live_leave", a.plugin)
        except Exception as exc:
            print(f"note: live cleanup: {exc}")


def run_imk(a: App, b: App, timeout: float) -> bool:
    """The plugin's own team features across both apps: its pictures, Undo, locks."""
    ok_all = True

    def check(name: str, ok: bool, detail: str = "") -> bool:
        nonlocal ok_all
        ok_all &= ok
        print(f"{name} {'ok' if ok else 'FAIL'}{(': ' + detail) if detail else ''}")
        return ok

    # Pictures: a page shows "Not on this PC yet" for a file the team has and this PC doesn't.
    def missing_on_b() -> Any:
        b.call("plugin_scope_sync", b.plugin, True)
        fa = {f["path"]: f.get("sha256") for f in a.data("files.list", prefix="").get("files") or []}
        fb = {f["path"]: f.get("sha256") for f in b.data("files.list", prefix="").get("files") or []}
        gone = sorted(p for p, sha in fa.items() if fb.get(p) != sha)
        return (fa, gone) if not gone else None

    got, t = wait(missing_on_b, timeout, 3.0)
    if t >= 0:
        fa = got[0]
        # Listed isn't enough: the page loads the bytes (team files carry no extension to pick pictures by).
        unread = [p for p, sha in sorted(fa.items())
                  if hashlib.sha256(base64.b64decode(b.data("files.get", path=p).get("b64") or "")).hexdigest() != sha]
        check("pictures on B", not unread, f"all {len(fa)} team files read back on B with the same sha256, in {t:.1f} s"
              if not unread else f"{len(unread)} of {len(fa)} listed but not readable on B: {unread[:4]}")
    else:
        fa = {f["path"]: f.get("sha256") for f in a.data("files.list", prefix="").get("files") or []}
        fb = {f["path"]: f.get("sha256") for f in b.data("files.list", prefix="").get("files") or []}
        gone = sorted(p for p, sha in fa.items() if fb.get(p) != sha)
        check("pictures on B", False, f"{len(gone)} of {len(fa)} not on B: {gone[:4]} · {stuck(b.status())}")

    # Undo from History on B: B's own change, undone on B, gone on A too.
    key = f"e2e.undo.{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        b.data("data.put", key=key, value={"probe": key})
        b.call("plugin_scope_push", b.plugin, f"e2e undo probe {key}")
        hist, t = wait(lambda: next((e for e in b.call("plugin_scope_history", b.plugin, {"limit": 20}).get("entries")
                                     or [] if ["doc", key] in (e.get("items") or [])), None), timeout, 2.0)
        if t < 0:
            check("restore on B", False, f"B's change never reached History: {stuck(b.status())}")
        else:
            out = b.call("plugin_scope_restore", b.plugin, {"undoSeq": hist["seq"], "message": "e2e undo"})
            if not out.get("ok", True):
                check("restore on B", False, f"undo #{hist['seq']}: {out.get('error')}")
            else:
                def undone() -> Any:
                    a.call("plugin_scope_pull", a.plugin)
                    return (b.data("data.get", key=key).get("value") is None
                            and a.data("data.get", key=key).get("value") is None) or None

                _, t2 = wait(undone, timeout, 3.0)
                check("restore on B", t2 >= 0, f"undo #{hist['seq']} on B, gone on A in {t2:.1f} s" if t2 >= 0 else
                      f"undo #{hist['seq']} answered {json.dumps(out)[:160]}, value still on "
                      f"{'B' if b.data('data.get', key=key).get('value') is not None else 'A'}")
    finally:
        try:
            if b.data("data.get", key=key).get("value") is not None:
                b.data("data.delete", key=key)
        except Exception as exc:
            print(f"note: undo probe cleanup on B: {exc}")

    # Locks: a control A is pressing (live hold) and an item A locked both show on B.
    la = a.live()
    a_joined = not la.get("on")
    if a_joined:
        la = a.call("plugin_live_join", a.plugin, "")
    room = str(la.get("room") or "")
    lb = b.live()
    b_was = str(lb.get("room") or "") if lb.get("on") else ""
    anchor, unit = "e2e-probe-control", f"e2e-lock-{int(time.time())}"
    try:
        b.call("plugin_live_join", b.plugin, room)
        b.mark()
        # Greyed at once by the ducky.hold live message; kept by A's presence, which the
        # page renews every 10 s (a hold not renewed for 30 s is gone), so renew here too.
        a.call("plugin_live_hold", a.plugin, anchor, True, 0.0, "")
        seen: list[dict[str, Any]] = []
        renewed = [time.monotonic()]

        def live_hold() -> Any:
            seen.extend(b.events())
            return next((e for e in seen if e.get("type") == "live_message" and e.get("topic") == "ducky.hold"
                         and (e.get("data") or {}).get("anchor") == anchor), None)

        def presence_hold() -> Any:
            if time.monotonic() - renewed[0] >= 10:
                a.call("plugin_live_hold", a.plugin, anchor, True, 0.0, "")
                renewed[0] = time.monotonic()
            return next((h for h in (b.call("plugin_live_holds", b.plugin).get("holds") or [])
                         if h.get("anchor") == anchor), None)

        _, t = wait(live_hold, 20, 0.5)
        if t < 0:  # B may still be linking: one more press once it is
            a.call("plugin_live_hold", a.plugin, anchor, True, 0.0, "")
            _, t = wait(live_hold, 20, 0.5)
        check("hold grey on B (live)", t >= 0, f"{t:.1f} s" if t >= 0 else "no ducky.hold from A on B's page in 40 s")
        _, t = wait(presence_hold, timeout, 2.0)
        check("hold grey on B (presence)", t >= 0, f"{t:.1f} s" if t >= 0 else
              f"B's plugin_live_holds never had A's control in {timeout:.0f} s")
        lk = a.call("plugin_scope_lock", a.plugin, unit, "e2e probe")
        if not lk.get("ok", True):
            check("lock on B", False, f"A lock: {lk.get('error')}")
        else:
            seen, t = wait(lambda: next((x for x in b.call("plugin_scope_activity", b.plugin).get("locks") or []
                                         if unit in json.dumps(x)), None), timeout, 2.0)
            check("lock on B", t >= 0, f"{t:.1f} s" if t >= 0 else "B's locks never had A's lock")
    finally:
        for step in (lambda: a.call("plugin_live_hold", a.plugin, anchor, False, 0.0, ""),
                     lambda: a.call("plugin_scope_unlock", a.plugin, unit),
                     lambda: b.call("plugin_live_join", b.plugin, b_was) if b_was and b_was != room
                     else (b.call("plugin_live_leave", b.plugin) if not b_was else None),
                     lambda: a.call("plugin_live_leave", a.plugin) if a_joined else None):
            try:
                step()
            except Exception as exc:
                print(f"note: lock cleanup: {exc}")
    return ok_all


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", type=int, default=4199, help="app A's panel port")
    ap.add_argument("--b", type=int, default=4299, help="app B's panel port")
    ap.add_argument("--plugin", default="island-media-kit")
    ap.add_argument("--only", choices=("sync", "live", "imk"), default="")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds per waiting stage")
    args = ap.parse_args()
    a, b = App("A", args.a, args.plugin), App("B", args.b, args.plugin)
    try:
        why = same_team(a, b)
    except Exception as exc:
        print(f"FAIL setup: {exc}")
        return 1
    if why:
        print(f"FAIL {why}")
        return 1
    ok = True
    if args.only in ("", "sync"):
        print("== sync")
        ok &= run_sync(a, b, args.timeout)
    if args.only in ("", "live"):
        print("== live")
        ok &= run_live(a, b, args.timeout)
    if args.only in ("", "imk"):
        print("== imk")
        ok &= run_imk(a, b, args.timeout)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
