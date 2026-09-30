"""PanelApi surface for Workflows (graphs, owners, catalog, test run)."""

from __future__ import annotations

from typing import Any


def _refused(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc) or "Not allowed"}


class PanelApiAutomationsMixin:
    def list_workflow_nodes(self) -> dict[str, Any]:
        from backend.automations.catalog import list_nodes

        return {"ok": True, "nodes": list_nodes()}

    def get_workflow_tools_catalog(self) -> dict[str, Any]:
        """Host tools a Call tool node can run. Never connects nested MCP plugins
        (that is the Settings catalog); run it as a bridge job all the same."""
        from frontend.ui_web.mcp_catalog import build_workflow_tool_catalog

        return build_workflow_tool_catalog()

    def list_workflows(self) -> dict[str, Any]:
        from backend.automations.store import list_workflows

        return {"ok": True, "workflows": list_workflows()}

    def workflow_owners(self, refresh: bool = False) -> dict[str, Any]:
        """Folders for the list. ``refresh`` asks the Store for the account's teams
        (one hub call, when the view opens)."""
        from backend.automations import team

        try:
            return team.refresh_teams() if refresh else team.owners()
        except Exception as exc:
            return _refused(exc)

    def workflow_sync(self, force: bool = False) -> dict[str, Any]:
        """Team rounds while the Workflows view is open; the engine rate-limits."""
        from backend.automations import team

        try:
            return team.sync(force=bool(force))
        except Exception as exc:
            return _refused(exc)

    def workflow_open_web(self, team_id: str) -> dict[str, Any]:
        from backend.automations import team

        try:
            return team.open_web(str(team_id or ""))
        except Exception as exc:
            return _refused(exc)

    def import_local_workflows(self) -> dict[str, Any]:
        from backend.automations import team

        try:
            return team.import_local()
        except (PermissionError, ValueError) as exc:
            return _refused(exc)

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        from backend.automations.store import get_workflow

        wf = get_workflow(workflow_id)
        if wf is None:
            return {"ok": False, "error": "workflow not found"}
        return {"ok": True, "workflow": wf}

    def list_workflow_versions(self, workflow_id: str) -> dict[str, Any]:
        from backend.automations.versions import list_versions
        return {"ok": True, "versions": list_versions(workflow_id)}

    def get_workflow_version(self, workflow_id: str, version_id: str) -> dict[str, Any]:
        from backend.automations.versions import get_version
        doc = get_version(workflow_id, version_id)
        return {"ok": True, "workflow": doc} if doc else {"ok": False, "error": "Version not found"}

    def save_workflow(self, doc: dict[str, Any] | None = None, owner: str = "", **extra: Any) -> dict[str, Any]:
        from backend.automations.store import save_workflow

        payload = dict(doc or {})
        payload.update(extra)
        try:
            return {"ok": True, "workflow": save_workflow(payload, owner=owner)}
        except (PermissionError, ValueError) as exc:
            return _refused(exc)

    def copy_workflow(self, workflow_id: str, owner: str, move: bool = False) -> dict[str, Any]:
        from backend.automations.store import copy_workflow

        try:
            return {"ok": True, "workflow": copy_workflow(workflow_id, owner, move=bool(move))}
        except KeyError:
            return {"ok": False, "error": "workflow not found"}
        except (PermissionError, ValueError) as exc:
            return _refused(exc)

    def set_workflow_run_here(self, workflow_id: str, on: bool) -> dict[str, Any]:
        from backend.automations.store import set_run_here

        wf = set_run_here(workflow_id, bool(on))
        return {"ok": True, "workflow": wf} if wf else {"ok": False, "error": "workflow not found"}

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        from backend.automations.store import delete_workflow

        try:
            ok = delete_workflow(workflow_id)
        except PermissionError as exc:
            return _refused(exc)
        return {"ok": True} if ok else {"ok": False, "error": "workflow not found"}

    def run_workflow(
        self,
        workflow_id: str,
        prompt: str = "",
        files: list[Any] | None = None,
        caller_conv_id: str = "",
        payload: dict[str, Any] | None = None,
        trigger_id: str = "",
        starter_id: str = "",
    ) -> dict[str, Any]:
        from backend.automations.runner import run_workflow

        return run_workflow(
            workflow_id,
            trigger_id=trigger_id,
            payload=payload or {},
            starter_id=starter_id,
            prompt=prompt,
            files=files,
            caller_conv_id=caller_conv_id,
        )

    def emit_workflow_trigger(self, trigger_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.automations.runner import emit_trigger

        return emit_trigger(trigger_id, payload or {})

    def list_workflow_templates(self) -> dict[str, Any]:
        from backend.automations.templates import list_templates

        return {"ok": True, "templates": list_templates()}

    def save_workflow_template(
        self,
        name: str,
        description: str = "",
        icon: str = "⚡",
        graph_json: str = "",
        template_id: str = "",
    ) -> dict[str, Any]:
        from backend.automations.templates import save_custom

        graph: Any = {}
        raw = (graph_json or "").strip()
        if raw:
            import json

            try:
                graph = json.loads(raw)
            except json.JSONDecodeError as exc:
                return {"ok": False, "error": f"bad graph_json: {exc}"}
        try:
            row = save_custom(
                name,
                description=description,
                icon=icon,
                graph=graph,
                template_id=template_id,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "template": row}

    def delete_workflow_template(self, template_id: str) -> dict[str, Any]:
        from backend.automations.templates import delete_custom

        if not delete_custom(template_id):
            return {"ok": False, "error": "template not found"}
        return {"ok": True}

    def list_generated_images(self) -> dict[str, Any]:
        from frontend.ui_web.generated_images import list_generated_images

        return {"ok": True, "images": list_generated_images()}

    def get_generated_image_attachment(self, name: str) -> dict[str, Any]:
        from frontend.ui_web.generated_images import attachment_from_path, resolve_generated_image_path

        try:
            att = attachment_from_path(resolve_generated_image_path(name))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not att:
            return {"ok": False, "error": "not an image"}
        return {"ok": True, "attachment": att}
