"""Locked nodes and groups, as the editor shows them.

A node is locked when it has ``locked: true`` or sits in a locked group (or a group
inside one). The editor won't move, rewire, edit or delete it; agents saving a graph
over MCP are held to the same rule unless the user agreed (``locked_changes``).
"""

from __future__ import annotations

import math
from typing import Any

from backend.automations.store import normalize_graph

# What a save may not change about a locked node or group.
_NODE_FIELDS = ("type", "config", "label", "description", "color", "icon", "locked", "width")
_GROUP_FIELDS = ("name", "node_ids", "parent_id", "color", "icon", "locked")


def group_members(groups: list[dict[str, Any]], group_id: str) -> list[str]:
    """Every node in a group, nested groups included (outer nodes first)."""
    out: list[str] = []
    todo, seen = [group_id], set()
    while todo:
        gid = todo.pop(0)
        if gid in seen:
            continue
        seen.add(gid)
        group = next((g for g in groups if g.get("id") == gid), None)
        if group is None:
            continue
        out += [str(n) for n in group.get("node_ids") or []]
        todo += [str(g["id"]) for g in groups if g.get("parent_id") == gid]
    return out


def _locked_groups(groups: dict[str, dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for gid in groups:
        at, seen = gid, set()
        while at and at in groups and at not in seen:
            seen.add(at)
            if groups[at].get("locked"):
                out.add(gid)
                break
            at = str(groups[at].get("parent_id") or "")
    return out


def locked_ids(graph: Any) -> tuple[set[str], set[str]]:
    """(locked node ids, locked group ids), counting what a locked group covers."""
    clean = normalize_graph(graph)
    groups = {g["id"]: g for g in clean.get("groups") or []}
    locked_groups = _locked_groups(groups)
    nodes = {n["id"] for n in clean["nodes"] if n.get("locked")}
    for gid in locked_groups:
        nodes.update(groups[gid]["node_ids"])
    return nodes, locked_groups


def _same_spot(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(math.isclose(float(a.get(k) or 0), float(b.get(k) or 0), abs_tol=1e-6) for k in ("x", "y"))


def _wires(graph: dict[str, Any], node_id: str) -> set[tuple[str, ...]]:
    return {(e["source"], e["target"], e["kind"], e.get("source_pin", ""), e.get("target_pin", "")) for e in graph["edges"] if node_id in (e["source"], e["target"])}


def _home(graph: dict[str, Any], node_id: str) -> str:
    return next((g["id"] for g in graph.get("groups") or [] if node_id in g["node_ids"]), "")


def locked_changes(old: Any, new: Any) -> list[str]:
    """Names of the locked nodes and groups in ``old`` that ``new`` moves, edits, rewires,
    regroups or removes. Empty when every lock is respected."""
    before, after = normalize_graph(old), normalize_graph(new)
    nodes_before = {n["id"]: n for n in before["nodes"]}
    nodes_after = {n["id"]: n for n in after["nodes"]}
    groups_before = {g["id"]: g for g in before.get("groups") or []}
    groups_after = {g["id"]: g for g in after.get("groups") or []}
    locked_nodes, locked_groups = locked_ids(before)
    changed: list[str] = []
    for nid, node in nodes_before.items():
        if nid not in locked_nodes:
            continue
        now = nodes_after.get(nid)
        if (
            now is None
            or not _same_spot(node, now)
            or any(node.get(k) != now.get(k) for k in _NODE_FIELDS)
            or _wires(before, nid) != _wires(after, nid)
            or _home(before, nid) != _home(after, nid)
        ):
            changed.append(node.get("label") or node["type"])
    for gid in sorted(locked_groups):
        group, now = groups_before[gid], groups_after.get(gid)
        if now is None or any(group.get(k) != now.get(k) for k in _GROUP_FIELDS):
            changed.append(f"group {group['name']}")
    return changed


def changed_nodes(old: Any, new: Any) -> list[str]:
    """Ids of nodes ``new`` adds or changes (moved, edited, rewired): what to show the user."""
    before, after = normalize_graph(old), normalize_graph(new)
    nodes_before = {n["id"]: n for n in before["nodes"]}
    out: list[str] = []
    for node in after["nodes"]:
        was = nodes_before.get(node["id"])
        if (
            was is None
            or not _same_spot(was, node)
            or any(was.get(k) != node.get(k) for k in _NODE_FIELDS)
            or _wires(before, node["id"]) != _wires(after, node["id"])
        ):
            out.append(node["id"])
    return out
