"""Swarm build: turn a confirmed ``swarm_preview.build_preview`` into the plan, groups and seats."""

from __future__ import annotations

import json
from typing import Any, Optional

from backend.tools.panel.swarm_preview import DONE_LINE, walk_groups, walk_seats


def _loads(text: str) -> dict[str, Any]:
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        data = json.loads(data["result"])
    if not isinstance(data, dict) or data.get("ok") is False:
        raise ValueError(str((data or {}).get("error") if isinstance(data, dict) else data))
    return data


class PanelSwarmApi:
    """The live calls a build makes, over the existing group and plan tools."""

    def caller(self) -> str:
        from backend.tools.panel.ducky_panel import _resolve_plan_chat_id

        return _resolve_plan_chat_id("")

    def group_create(self, name: str, parent_folder_id: str = "") -> dict[str, Any]:
        from backend.tools.panel.ducky_panel import ducky_group_create

        res = _loads(ducky_group_create(name=name, parent_folder_id=parent_folder_id))
        return {"id": res.get("id") or "", "folder_id": res.get("folder_id") or ""}

    def add_leader(self, group_id: str, conv_id: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_group_add_member

        _loads(ducky_group_add_member(group_id=group_id, conv_id=conv_id, as_leader=True, move_folder=True))

    def rename_chat(self, conv_id: str, title: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_rename_chat

        _loads(ducky_rename_chat(conv_id=conv_id, title=title))

    def ensure_plan(self, chat_id: str, goal: str) -> None:
        from backend.agent.coding_agents.plans import load_plan_view
        from backend.tools.panel.ducky_panel import _project_root, ducky_create_plan

        try:
            plan = load_plan_view(chat_id, project_root=_project_root())
        except ValueError:
            plan = None
        if not plan:
            _loads(ducky_create_plan(title=goal, overview=f"Swarm: {goal}", nodes=[], chat_id=chat_id))

    def plan_add_node(self, chat_id: str, content: str, parent_id: str = "", kind: str = "step",
                      body_markdown: str = "") -> str:
        from backend.tools.panel.ducky_panel import ducky_plan_add_node

        res = _loads(ducky_plan_add_node(content=content, parent_id=parent_id, chat_id=chat_id, kind=kind,
                                         body_markdown=body_markdown))
        return str((res.get("node") or {}).get("id") or "")

    def invite(self, group_id: str, profile: str, name: str, model: str,
               write_allowed: Optional[list[str]]) -> str:
        from backend.tools.panel.ducky_panel import ducky_group_invite

        res = _loads(ducky_group_invite(group_id=group_id, ducky=profile, write_allowed=write_allowed,
                                        name=name, model=model))
        return str((res.get("member") or {}).get("member_conv_id") or "")

    def set_muted(self, conv_id: str, muted: bool) -> None:
        from backend.tools.panel.ducky_panel import ducky_set_muted

        _loads(ducky_set_muted(conv_id=conv_id, muted=muted))

    def assign(self, chat_id: str, node_id: str, assignee: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_plan_update_node

        _loads(ducky_plan_update_node(node_id=node_id, chat_id=chat_id, assignee=assignee))


def build_swarm(preview: dict[str, Any], api: Any) -> dict[str, Any]:
    """Build *preview* exactly: (1) root group + caller as lead, (2) one sub plan per job with
    its steps, no assignee, (3) nested groups and seats with lanes, then mute, (4) assign."""
    goal = preview["goal"]
    tree = preview["tree"]
    lead = api.caller()
    if not lead:
        raise ValueError("No calling chat: ducky_swarm_create must run in the lead's chat.")
    root = api.group_create(goal)
    api.add_leader(root["id"], lead)
    api.rename_chat(lead, f"Lead: {goal}")

    api.ensure_plan(lead, goal)
    sections: dict[str, str] = {}
    for seat in walk_seats(tree):
        job = preview["jobs"][seat["name"]]
        body = "\n".join(x for x in (job["purpose"], job["task"],
                                     f"Files: {', '.join(job['paths'])}" if job["paths"] else "", DONE_LINE) if x)
        sid = api.plan_add_node(lead, seat["sub_plan"]["title"], kind="subplan", body_markdown=body)
        for step in seat["sub_plan"]["steps"]:  # exactly the previewed steps, edits included
            api.plan_add_node(lead, step["content"], parent_id=sid, body_markdown=step["body_markdown"])
        sections[seat["name"]] = sid
        seat["sub_plan"]["id"] = sid

    def seat_in(group_id: str, seat: dict[str, Any]) -> None:
        seat["conv_id"] = api.invite(group_id, seat["profile"], seat["name"], seat["model"], seat["paths"] or None)
        seat["created"] = True

    def make(node: dict[str, Any], parent_folder: str) -> None:
        made = api.group_create(node["group"], parent_folder)
        node["group_id"], node["created"] = made["id"], True
        for seat in node["seats"]:
            seat_in(made["id"], seat)
        for sub in node["groups"]:
            make(sub, made["folder_id"])

    for node in tree:
        if "group" in node:
            make(node, root["folder_id"])
        else:
            seat_in(root["id"], node)
    for group in walk_groups(tree):
        if group["muted"]:
            api.set_muted(group["group_id"], True)
    for seat in walk_seats(tree):
        api.assign(lead, sections[seat["name"]], seat["conv_id"])
    return {"root_group_id": root["id"], "lead": lead, "tree": tree}
