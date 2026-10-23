"""Ducky looking at itself: what uses this PC's CPU and memory, which of it is Ducky, why
the app may feel slow, and the safe fixes (``ducky_health`` / ``ducky_self_care``).

Runs in the Ducky window's process (agents' tool servers ask over the panel API), so the
numbers are the app's own. One snapshot samples CPU over one second; nothing here keeps
history or a thread, so looking never becomes a cost itself.
"""

from __future__ import annotations

import gc
import json
import os
import time
from pathlib import Path
from typing import Any

_MB = 1024 * 1024
_GB = 1024 * _MB
_DUCKY_NAMES = ("uefn-ducky",)
_UEFN_NAMES = ("unrealeditorfortnite", "unrealeditor")


def _mb(value: float) -> float:
    return round(float(value) / _MB, 1)


def _app_dir() -> Path:
    from frontend.settings import default_app_data_dir

    return default_app_data_dir()


def _folder_mb(path: Path, cap_files: int = 60_000) -> float:
    from backend.sandbox.paths import dir_size

    return _mb(dir_size(path, cap_files=cap_files)) if path.exists() else 0.0


def _role(cmdline: list[str]) -> str:
    args = " ".join(cmdline[1:]).lower()
    if "--shared-daemon" in args:
        return "shared tool server"
    if "--adapter" in args:
        return "IDE adapter"
    if " bridge" in f" {args}" or args.startswith("bridge"):
        return "tool server (bridge)"
    return "app"


def _sample(procs: list[Any]) -> dict[int, float]:
    """CPU % per process over one second (one sleep for all of them)."""
    import psutil

    for p in procs:
        try:
            p.cpu_percent(interval=None)
        except psutil.Error:
            pass
    time.sleep(1.0)
    out: dict[int, float] = {}
    for p in procs:
        try:
            out[p.pid] = p.cpu_percent(interval=None)
        except psutil.Error:
            pass
    return out


def snapshot(detail: bool = False) -> dict[str, Any]:
    import psutil

    me = psutil.Process(os.getpid())
    try:
        children = me.children(recursive=True)
    except psutil.Error:
        children = []
    every = list(psutil.process_iter(["name", "memory_info", "create_time", "ppid", "cmdline", "exe"]))
    ducky = [p for p in every if str(p.info.get("name") or "").lower().startswith(_DUCKY_NAMES)]
    uefn = [p for p in every if str(p.info.get("name") or "").lower().startswith(_UEFN_NAMES)]
    cpu = _sample([me, *children, *ducky, *uefn])
    ncpu = psutil.cpu_count() or 1

    def info(p: Any) -> dict[str, Any]:
        try:
            mem = p.memory_info()
            row = {"pid": p.pid, "name": p.name(), "memory_mb": _mb(mem.rss), "cpu_percent": round(cpu.get(p.pid, 0.0), 1)}
            if hasattr(mem, "private"):
                row["private_mb"] = _mb(mem.private)
            return row
        except psutil.Error:
            return {"pid": p.pid, "gone": True}

    with me.oneshot():
        mem = me.memory_info()
        app = {
            "pid": me.pid,
            "memory_mb": _mb(mem.rss),
            "private_mb": _mb(getattr(mem, "private", 0)),
            "threads": me.num_threads(),
            "handles": me.num_handles() if hasattr(me, "num_handles") else None,
            "cpu_percent": round(cpu.get(me.pid, 0.0), 1),
            "uptime_min": round((time.time() - me.create_time()) / 60, 1),
        }
    by_name: dict[str, dict[str, Any]] = {}
    for p in children:
        row = info(p)
        if row.get("gone"):
            continue
        slot = by_name.setdefault(row["name"], {"name": row["name"], "count": 0, "memory_mb": 0.0, "cpu_percent": 0.0})
        slot["count"] += 1
        slot["memory_mb"] = round(slot["memory_mb"] + row["memory_mb"], 1)
        slot["cpu_percent"] = round(slot["cpu_percent"] + row["cpu_percent"], 1)
    helpers = sorted(by_name.values(), key=lambda r: -r["memory_mb"])

    alive = {p.pid for p in every}
    ducky_rows: list[dict[str, Any]] = []
    for p in ducky:
        if p.pid == me.pid:
            continue
        row = info(p)
        if row.get("gone"):
            continue
        cmd = list(p.info.get("cmdline") or [])
        ppid = int(p.info.get("ppid") or 0)
        row.update({"role": _role(cmd), "exe": str(p.info.get("exe") or ""),
                    "orphan": _role(cmd) not in ("app", "shared tool server") and ppid not in alive})
        ducky_rows.append(row)

    vm = psutil.virtual_memory()
    top = sorted(
        ({"name": str(p.info.get("name") or "?"), "memory_mb": _mb(getattr(p.info.get("memory_info"), "rss", 0) or 0)}
         for p in every if p.info.get("memory_info")),
        key=lambda r: -r["memory_mb"],
    )
    merged: dict[str, float] = {}
    for row in top:
        merged[row["name"]] = merged.get(row["name"], 0.0) + row["memory_mb"]
    top_apps = sorted(({"name": k, "memory_mb": round(v, 1)} for k, v in merged.items()), key=lambda r: -r["memory_mb"])[:8]

    out: dict[str, Any] = {
        "ok": True,
        "app": app,
        "helpers": helpers[:12],
        "other_ducky_processes": ducky_rows[:20],
        "uefn": [info(p) for p in uefn][:3],
        "pc": {"memory_used_percent": vm.percent, "memory_total_gb": round(vm.total / _GB, 1),
               "memory_free_gb": round(vm.available / _GB, 1), "cpu_percent": round(psutil.cpu_percent(None), 1),
               "cpus": ncpu, "top_apps": top_apps},
        "sandboxes": _sandboxes(),
        "terminals": _terminals(),
        "storage": _storage(),
        "running_agents": _running_agents(),
    }
    if detail:
        out["perf"] = _perf()
    out["findings"] = findings(out)
    return out


def _sandboxes() -> dict[str, Any]:
    try:
        from backend.sandbox import paths, service

        progs = service.all_programs()
        return {"count": len(paths.list_sandboxes()), "programs": progs[:20],
                "programs_memory_mb": round(sum(float(p.get("memory_mb") or 0) for p in progs), 1)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _terminals() -> dict[str, Any]:
    try:
        from frontend.ui_web.terminal import get_terminal_manager

        rows = get_terminal_manager().list_sessions()
        return {"open": len(rows), "agent_owned": sum(1 for r in rows if r.get("conv_id") or r.get("chat"))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _running_agents() -> int:
    try:
        from frontend.ui_web.agent_modes import list_running_agents

        return len(list(list_running_agents()))
    except Exception:
        return 0


def _storage() -> dict[str, Any]:
    base = _app_dir()
    out: dict[str, Any] = {}
    for name in ("chats", "sandboxes", "cache", "perf", "logs", "tools"):
        out[f"{name}_mb"] = _folder_mb(base / name)
    for name in ("ducky.db", "ducky.db-wal"):
        try:
            out[name.replace(".", "_").replace("-", "_") + "_mb"] = _mb((base / name).stat().st_size)
        except OSError:
            pass
    return out


def _perf() -> Any:
    try:
        from frontend.perf_trace import read_latest_report

        report = read_latest_report() or {}
        text = json.dumps(report, default=str)
        if len(text) < 6000:
            return report
        return {"note": "perf report trimmed (ducky_perf_report has all of it)", "excerpt": text[:6000]}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def findings(snap: dict[str, Any]) -> list[dict[str, str]]:
    """Plain-words causes, most important first, each with the fix (a self-care action or a step)."""
    out: list[dict[str, str]] = []
    app = snap.get("app") or {}
    pc = snap.get("pc") or {}
    ncpu = int(pc.get("cpus") or 1)
    app_cpu_pc = float(app.get("cpu_percent") or 0) / ncpu
    if app_cpu_pc > 15:
        out.append({"severity": "high", "what": f"Ducky's window process uses {app_cpu_pc:.0f}% of the PC's CPU.",
                    "why": "Something in the app is busy while it should idle (a stuck loop, a flood of UI updates).",
                    "fix": "ducky_perf_report names the slowest UI work; ducky_memory_report(start_trace=true) shows what grows."})
    if float(app.get("private_mb") or app.get("memory_mb") or 0) > 2048:
        out.append({"severity": "high", "what": f"Ducky's window process holds {app.get('private_mb') or app.get('memory_mb')} MB.",
                    "why": "Normal is a few hundred MB; this much means something keeps growing.",
                    "fix": "ducky_memory_report(start_trace=true), wait a minute, call it again: 'grew' names the cause."})
    if int(app.get("handles") or 0) > 15000:
        out.append({"severity": "medium", "what": f"{app['handles']} open handles in Ducky's window process.",
                    "why": "Handles that only climb are a leak (files, sockets, threads not closed).",
                    "fix": "ducky_memory_report and ducky_perf_report; restart Ducky if it keeps climbing."})
    helpers = snap.get("helpers") or []
    web = next((h for h in helpers if "webview2" in h["name"].lower()), None)
    if web and float(web["memory_mb"]) > 3000:
        out.append({"severity": "medium", "what": f"Ducky's browser engine (WebView2) uses {web['memory_mb']} MB in {web['count']} processes.",
                    "why": "Many open tabs, a heavy Browser-tab page, or a long chat with many pictures.",
                    "fix": "Close Browser tabs and chats you are not using."})
    orphans = [p for p in snap.get("other_ducky_processes") or [] if p.get("orphan")]
    if orphans:
        out.append({"severity": "medium", "what": f"{len(orphans)} leftover Ducky tool servers whose IDE or agent is gone "
                                                 f"({round(sum(float(p.get('memory_mb') or 0) for p in orphans))} MB).",
                    "why": "An IDE or agent closed without stopping its Ducky bridge.",
                    "fix": "ducky_self_care(action='stop_orphan_bridges')"})
    sb = snap.get("sandboxes") or {}
    heavy = [p for p in sb.get("programs") or [] if float(p.get("memory_mb") or 0) > 1024 or float(p.get("cpu_percent") or 0) / ncpu > 25]
    if heavy:
        names = ", ".join(f"{p['name']} ({p.get('memory_mb')} MB, {p.get('cpu_percent')}% CPU)" for p in heavy[:4])
        out.append({"severity": "medium", "what": f"Sandbox programs are heavy: {names}.",
                    "why": "A program an agent started in a sandbox is still running.",
                    "fix": "ducky_self_care(action='stop_sandbox', target='<chat id or all>')"})
    terms = snap.get("terminals") or {}
    if int(terms.get("agent_owned") or 0) > 6:
        out.append({"severity": "low", "what": f"{terms['agent_owned']} agent terminals are open.",
                    "why": "Each keeps a shell and its console alive.",
                    "fix": "ducky_self_care(action='close_idle_terminals')"})
    storage = snap.get("storage") or {}
    if float(storage.get("ducky_db_wal_mb") or 0) > 256:
        out.append({"severity": "low", "what": f"The database's write-ahead log is {storage['ducky_db_wal_mb']} MB.",
                    "why": "It is folded back into ducky.db when nothing holds it; a long-running reader stops that.",
                    "fix": "Restart Ducky when convenient."})
    if float(storage.get("cache_mb") or 0) > 1024 or float(storage.get("sandboxes_mb") or 0) > 10240:
        out.append({"severity": "low", "what": f"Caches {storage.get('cache_mb')} MB, sandboxes {storage.get('sandboxes_mb')} MB on disk.",
                    "why": "Downloads and sandboxes that are no longer needed.",
                    "fix": "ducky_self_care(action='trim_caches') and ducky_self_care(action='prune_sandboxes')"})
    for u in snap.get("uefn") or []:
        if float(u.get("private_mb") or u.get("memory_mb") or 0) > 30 * 1024:
            out.append({"severity": "high", "what": f"UEFN uses {round(float(u.get('private_mb') or u['memory_mb']) / 1024, 1)} GB.",
                        "why": "UEFN's editor memory only grows during a long session (garbage collections then stall it "
                               "for seconds); it is not Ducky.",
                        "fix": "Save, then reopen UEFN (ducky_restart_uefn) to get the memory back."})
    used = float(pc.get("memory_used_percent") or 0)
    if used > 88:
        ducky_mb = float(app.get("memory_mb") or 0) + sum(float(h["memory_mb"]) for h in helpers) + sum(
            float(p.get("memory_mb") or 0) for p in snap.get("other_ducky_processes") or [])
        biggest = (pc.get("top_apps") or [{}])[0]
        out.append({"severity": "high" if used > 95 else "medium",
                    "what": f"The PC's memory is {used:.0f}% used; Ducky's share is about {round(ducky_mb / 1024, 1)} GB.",
                    "why": f"The biggest user is {biggest.get('name', '?')} ({round(float(biggest.get('memory_mb') or 0) / 1024, 1)} GB)."
                           + (" It's mostly not Ducky." if ducky_mb < 0.15 * float(pc.get("memory_total_gb") or 1) * 1024 else ""),
                    "fix": "Close what you don't need among the top apps listed."})
    if not out:
        out.append({"severity": "ok", "what": "Nothing in Ducky looks wrong right now.", "why": "CPU, memory, handles, helpers, "
                    "sandboxes and terminals are all in their normal range.", "fix": ""})
    order = {"high": 0, "medium": 1, "low": 2, "ok": 3}
    return sorted(out, key=lambda f: order.get(f["severity"], 9))


ACTIONS = ("stop_sandbox", "close_idle_terminals", "stop_orphan_bridges", "trim_caches", "prune_sandboxes", "collect_garbage")


def self_care(action: str, target: str = "") -> dict[str, Any]:
    import psutil

    before = psutil.Process(os.getpid()).memory_info().rss
    act = (action or "").strip()
    done: dict[str, Any] = {"ok": True, "action": act}
    if act == "stop_sandbox":
        from backend.sandbox import service

        if target and target != "all":
            done.update(service.stop(target))
        else:
            done["stopped"] = service.stop_everything()
    elif act == "close_idle_terminals":
        from frontend.ui_web.terminal import get_terminal_manager

        mgr = get_terminal_manager()
        # "now" pushed past the quiet time: every agent terminal that is done closes now;
        # running ones, ones waiting on a card and the person's own stay.
        done["closed"] = mgr.close_idle_agent_terminals(now=time.time() + 24 * 3600)
    elif act == "stop_orphan_bridges":
        me = os.getpid()
        alive = {p.pid for p in psutil.process_iter()}
        stopped = []
        for p in psutil.process_iter(["name", "ppid", "cmdline"]):
            name = str(p.info.get("name") or "").lower()
            if p.pid == me or not name.startswith(_DUCKY_NAMES):
                continue
            role = _role(list(p.info.get("cmdline") or []))
            if role in ("app", "shared tool server") or int(p.info.get("ppid") or 0) in alive:
                continue
            try:
                p.terminate()
                stopped.append({"pid": p.pid, "role": role})
            except psutil.Error:
                pass
        done["stopped"] = stopped
    elif act == "trim_caches":
        from backend.tools.core.web_video import cache_dir

        freed = 0
        for f in cache_dir().glob("*"):
            try:
                if f.is_file():
                    freed += f.stat().st_size
                    f.unlink()
            except OSError:
                pass
        done["freed_mb"] = _mb(freed)
    elif act == "prune_sandboxes":
        from backend.sandbox import service
        from backend.tools.panel.permission_prompt import _chat_exists

        done["removed"] = service.prune(chat_exists=_chat_exists)
    elif act == "collect_garbage":
        done["objects_freed"] = gc.collect()
    else:
        return {"ok": False, "error": f"action must be one of: {', '.join(ACTIONS)}."}
    after = psutil.Process(os.getpid()).memory_info().rss
    done["app_memory_mb"] = {"before": _mb(before), "after": _mb(after)}
    return done
