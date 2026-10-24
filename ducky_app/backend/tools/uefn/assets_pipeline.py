"""Asset pipeline tools: import/export, dependencies, folders, saving directories."""

from __future__ import annotations

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("uefn")
def create_folder(path: str, pretty: bool = False) -> str:
    """Create a content folder under the project's content_root. Never invent /Game/<Folder> paths."""
    return tool_json(send_command("create_folder", {"path": path}), pretty=pretty)


@plugin_mcp_tool("uefn")
def import_asset(source_file: str, destination_path: str, replace_existing: bool = True, pretty: bool = False) -> str:
    """Import a file (fbx/png/wav/...) from disk under content_root. Never an invented /Game/ path."""
    return tool_json(send_command("import_asset", {"source_file": source_file, "destination_path": destination_path, "replace_existing": replace_existing}), pretty=pretty)


@plugin_mcp_tool("uefn")
def export_asset(asset_path: str, output_directory: str, pretty: bool = False) -> str:
    """Export an asset to a folder on disk. Never into the UEFN project folder."""
    return tool_json(send_command("export_asset", {"asset_path": asset_path, "output_directory": output_directory}), pretty=pretty)


@plugin_mcp_tool("uefn")
def get_dependencies(asset_path: str, pretty: bool = False) -> str:
    """List what an asset references (its package dependencies). Not what uses it (get_referencers)."""
    return tool_json(send_command("get_dependencies", {"asset_path": asset_path}), pretty=pretty)


@plugin_mcp_tool("uefn")
def get_referencers(asset_path: str, pretty: bool = False) -> str:
    """List packages that reference an asset. Not what it references (get_dependencies)."""
    return tool_json(send_command("get_referencers", {"asset_path": asset_path}), pretty=pretty)


@plugin_mcp_tool("uefn")
def validate_uefn_asset(asset_path: str, usecase: str = "MANUAL", pretty: bool = False) -> str:
    """Run UEFN validators on one asset and return publish/cook blockers. Never a delete list.

    Prefer this over inferring blockers from get_dependencies alone — a
    /Script/NiagaraEditor dependency is supporting evidence, not proof of Custom HLSL.
    usecase: MANUAL|SCRIPT|SAVE|COMMANDLET|PRE_SUBMIT (default MANUAL).
    """
    return tool_json(
        send_command("validate_uefn_asset", {"asset_path": asset_path, "usecase": usecase}),
        pretty=pretty,
    )


@plugin_mcp_tool("uefn")
def fixup_redirectors(directory: str = "", pretty: bool = False) -> str:
    """Resolve redirectors under a directory (empty = project content_root). Never invent /Game/ paths."""
    return tool_json(send_command("fixup_redirectors", {"directory": directory}), pretty=pretty)


@plugin_mcp_tool("uefn")
def save_directory(directory: str = "", only_if_dirty: bool = True, pretty: bool = False) -> str:
    """Save assets under a directory (empty = project content_root). Never invent /Game/ paths."""
    return tool_json(send_command("save_directory", {"directory": directory, "only_if_dirty": only_if_dirty}), pretty=pretty)
