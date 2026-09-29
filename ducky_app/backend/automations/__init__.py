"""Desktop Workflows: graphs owned by Local or a team, runner, plugin nodes, panel-process scheduler."""

from backend.automations.catalog import list_nodes as list_workflow_nodes
from backend.automations.runner import emit_trigger, run_workflow
from backend.automations.store import (
    copy_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    save_workflow,
)

__all__ = [
    "copy_workflow",
    "delete_workflow",
    "emit_trigger",
    "get_workflow",
    "list_workflow_nodes",
    "list_workflows",
    "run_workflow",
    "save_workflow",
]
