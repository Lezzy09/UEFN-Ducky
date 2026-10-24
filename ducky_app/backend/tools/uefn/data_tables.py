"""Data table tools: inspect, create, and (re)fill DataTable assets."""

from __future__ import annotations

from typing import Optional

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("uefn")
def data_table_capabilities(pretty: bool = False) -> str:
    """Probe which DataTable classes/methods this UEFN build exposes. Run it first; never guess the API."""
    return tool_json(send_command("data_table_capabilities", {}), pretty=pretty)


@plugin_mcp_tool("uefn")
def list_data_tables(search: str = "", offset: int = 0, limit: int = 50, pretty: bool = False) -> str:
    """List DataTable assets in the project (search filter, paged). Does not read rows (get_data_table_rows)."""
    return tool_json(send_command("list_data_tables", {"search": search, "offset": offset, "limit": limit}), pretty=pretty)


@plugin_mcp_tool("uefn")
def get_data_table_info(data_table_path: str, pretty: bool = False) -> str:
    """Read a data table's row struct, row names and columns. Not row values (get_data_table_rows)."""
    return tool_json(send_command("get_data_table_info", {"data_table_path": data_table_path}), pretty=pretty)


@plugin_mcp_tool("uefn")
def get_data_table_rows(
    data_table_path: str,
    columns: Optional[list[str]] = None,
    row_names: Optional[list[str]] = None,
    offset: int = 0,
    limit: int = 30,
    pretty: bool = False,
) -> str:
    """Read rows as strings (paged). Never modifies the table.

    columns = row-struct field names; required if discovery is unavailable.
    """
    return tool_json(
        send_command(
            "get_data_table_rows",
            {
                "data_table_path": data_table_path,
                "columns": columns,
                "row_names": row_names,
                "offset": offset,
                "limit": limit,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("uefn")
def fill_data_table_from_json(data_table_path: str, json_string: str, pretty: bool = False) -> str:
    """REPLACE ALL rows of a data table from a JSON array (fields match the row struct). Not an append."""
    return tool_json(
        send_command("fill_data_table_from_json", {"data_table_path": data_table_path, "json_string": json_string}),
        pretty=pretty,
    )


@plugin_mcp_tool("uefn")
def fill_data_table_from_csv(data_table_path: str, csv_string: str, pretty: bool = False) -> str:
    """REPLACE ALL rows of a data table from CSV (header matches the row struct). Not an append."""
    return tool_json(
        send_command("fill_data_table_from_csv", {"data_table_path": data_table_path, "csv_string": csv_string}),
        pretty=pretty,
    )


@plugin_mcp_tool("uefn")
def create_data_table(asset_name: str, row_struct: str, folder: str = "", pretty: bool = False) -> str:
    """Create a DataTable for row_struct (struct name or user-struct path). Never invent /Game/ folders."""
    return tool_json(
        send_command("create_data_table", {"asset_name": asset_name, "row_struct": row_struct, "folder": folder}),
        pretty=pretty,
    )
