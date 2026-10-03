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

    def workflow_sync(self, force: bool = False, team_id: str = "", upload: bool = False) -> dict[str, Any]:
        """Team rounds while the Workflows view is open. A team id (Save, Update
        online) pushes that team's workflows and waits for the round."""
        from backend.automations import team

        try:
            return team.sync(force=bool(force), team_id=str(team_id or ""), upload=bool(upload))
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

        from backend.automations.media import refresh_links

        wf = get_workflow(workflow_id)
        if wf is None:
            return {"ok": False, "error": "workflow not found"}
        return {"ok": True, "workflow": refresh_links(wf)}

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

    def set_workflow_folder(self, workflow_id: str, folder: str = "") -> dict[str, Any]:
        """File a workflow in a folder of its owner (drag in the list)."""
        from backend.automations.store import set_folder

        try:
            wf = set_folder(workflow_id, folder)
        except (PermissionError, ValueError) as exc:
            return _refused(exc)
        return {"ok": True, "workflow": wf} if wf else {"ok": False, "error": "workflow not found"}

    def move_workflow_folder(self, owner: str, path: str, new_path: str = "") -> dict[str, Any]:
        """Rename or move a folder; ``new_path`` = its parent deletes it, keeping the workflows."""
        from backend.automations.store import move_folder

        try:
            return {"ok": True, "moved": move_folder(owner, path, new_path)}
        except (PermissionError, ValueError) as exc:
            return _refused(exc)

    def set_workflow_run_here(self, workflow_id: str, on: bool) -> dict[str, Any]:
        from backend.automations.store import set_run_here

        wf = set_run_here(workflow_id, bool(on))
        return {"ok": True, "workflow": wf} if wf else {"ok": False, "error": "workflow not found"}

    def clear_workflow_runs(self, workflow_id: str) -> dict[str, Any]:
        """Run log → Clear log: forget this PC's past runs of one workflow."""
        from backend.automations.store import clear_runs

        return {"ok": True} if clear_runs(workflow_id) else {"ok": False, "error": "workflow not found"}

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

    def run_workflow_node(self, workflow_id: str, node_id: str) -> dict[str, Any]:
        """Run this node only: what feeds it is reused from the last run (no paid repeats)."""
        from backend.automations.runner import run_node

        return run_node(workflow_id, node_id)

    def pick_workflow_folder(self) -> dict[str, Any]:
        """Save file nodes: the Windows folder picker."""
        win = getattr(self, "_window", None)
        if win is None:
            return {"ok": False, "error": "No window to open the picker from", "folder": ""}
        try:
            import webview

            try:
                folder_type = webview.FileDialog.FOLDER
            except AttributeError:
                folder_type = getattr(webview, "FOLDER_DIALOG", 20)
            picked = win.create_file_dialog(folder_type)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "folder": ""}
        folder = picked[0] if isinstance(picked, (list, tuple)) and picked else picked or ""
        return {"ok": True, "folder": str(folder or "")}

    def check_workflow_expression(self, expression: str = "") -> dict[str, Any]:
        """If / Expression nodes: '' when the condition parses, else what is wrong."""
        from backend.automations.expr import check

        error = check(str(expression or ""))
        return {"ok": not error, "error": error}

    def pick_workflow_files(self, accept: str = "any", multiple: bool = False) -> dict[str, Any]:
        """Input nodes: the Windows file picker, filtered to what the node takes."""
        from backend.automations.files import FILE_FILTERS, file_ref, kind_of, with_url

        win = getattr(self, "_window", None)
        if win is None:
            return {"ok": False, "error": "No window to open the picker from", "files": []}
        try:
            import webview

            try:
                open_type = webview.FileDialog.OPEN
            except AttributeError:
                open_type = getattr(webview, "OPEN_DIALOG", 10)
            picked = win.create_file_dialog(open_type, allow_multiple=bool(multiple), file_types=FILE_FILTERS.get(str(accept or "any"), FILE_FILTERS["any"]))
        except Exception as exc:
            return {"ok": False, "error": str(exc), "files": []}
        kind = str(accept or "any")
        return {"ok": True, "files": [with_url(file_ref(path, kind if kind != "any" else kind_of(path))) for path in (picked or [])]}

    def workflow_editor_prefs(self) -> dict[str, Any]:
        """Grid, snap, tool, panel sizes and zoom of the Workflows editor on this PC."""
        from backend.automations.editor_prefs import load

        return {"ok": True, "prefs": load()}

    def set_workflow_editor_prefs(self, prefs: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.automations.editor_prefs import save

        try:
            return {"ok": True, "prefs": save(dict(prefs or {}))}
        except ValueError as exc:
            return _refused(exc)

    def stop_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Stop button: end every run of this workflow on this PC now."""
        from backend.automations.runner import stop_workflow

        return {"ok": True, "stopped": stop_workflow(workflow_id)}

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
        category: str = "",
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
                category=category,
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
