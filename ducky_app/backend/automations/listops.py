"""List nodes (plan §6, Lists [P2]): make a list, pick an item, count, join, keep the
items an expression says yes to, and turn each item into something else."""

from __future__ import annotations

import json
from typing import Any

from backend.automations.expr import as_number, as_text, evaluate, truthy

_MAX_ITEMS = 10000


def as_list(value: Any) -> list[Any]:
    """A wired value as a list: a list as is, JSON text of a list, else one item."""
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
    if isinstance(value, dict) and not value.get("path"):
        return list(value.values())
    return [value]


def make(cfg: dict[str, Any], inputs: dict[str, Any], _payload: dict[str, Any]) -> dict[str, Any]:
    names = [str(name) for name in cfg.get("names") or []] or list(inputs)
    items = [inputs[name] for name in names if inputs.get(name) is not None]
    return {"ok": True, "outputs": {"list": items}}


def get_item(cfg: dict[str, Any], inputs: dict[str, Any], _payload: dict[str, Any]) -> dict[str, Any]:
    items = as_list(inputs.get("list"))
    raw = inputs.get("index", cfg.get("index", 0))
    index = as_number(raw if raw not in (None, "") else 0)
    if index != index or int(index) != index:  # NaN or a fraction
        raise ValueError(f"Index must be a whole number, not {as_text(raw)}.")
    index = int(index)
    if not items:
        raise ValueError("The list is empty.")
    if not -len(items) <= index < len(items):
        raise ValueError(f"There is no item {index}: the list has {len(items)} (first is 0, last is -1).")
    return {"ok": True, "outputs": {"item": items[index]}}


def count(_cfg: dict[str, Any], inputs: dict[str, Any], _payload: dict[str, Any]) -> dict[str, Any]:
    value = inputs.get("list")
    size = len(value) if isinstance(value, (str, dict)) and not (isinstance(value, dict) and value.get("path")) else len(as_list(value))
    return {"ok": True, "outputs": {"count": size}}


def join(cfg: dict[str, Any], inputs: dict[str, Any], _payload: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("separator", cfg.get("separator"))
    separator = ", " if raw is None else str(raw).replace("\\n", "\n")
    return {"ok": True, "outputs": {"text": separator.join(as_text(item) for item in as_list(inputs.get("list")))}}


def _each(cfg: dict[str, Any], inputs: dict[str, Any], payload: dict[str, Any]):
    source = str(cfg.get("expression") or "").strip()
    if not source:
        raise ValueError("Write the expression in the details: item is each value, index its place.")
    items = as_list(inputs.get("list"))
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"That list has {len(items)} items; the most is {_MAX_ITEMS}.")
    base = {key: value for key, value in payload.items() if isinstance(key, str) and not key.startswith("_")}
    base.update({key: value for key, value in inputs.items() if key != "list"})
    for index, item in enumerate(items):
        yield item, evaluate(source, {**base, "item": item, "index": index, "items": items})


def filter_items(cfg: dict[str, Any], inputs: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    kept = [item for item, verdict in _each(cfg, inputs, payload) if truthy(verdict)]
    return {"ok": True, "outputs": {"list": kept, "count": len(kept)}}


def transform(cfg: dict[str, Any], inputs: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "outputs": {"list": [value for _item, value in _each(cfg, inputs, payload)]}}


HANDLERS = {
    "list.make": make,
    "list.get": get_item,
    "list.count": count,
    "list.join": join,
    "list.filter": filter_items,
    "list.map": transform,
}
