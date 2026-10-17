"""Three-way merge of JSON docs: the last synced version (base), the team's (theirs) and
this PC's unsent edit (mine).

- Objects merge key by key, recursively.
- Arrays whose elements are all objects with a unique ``id`` merge by id: the result
  follows theirs' order, mine's new ids are appended in mine's order, and ids either
  side removed are removed. Elements on both sides merge recursively.
- With ``set_arrays`` an array of plain values (strings, numbers) merges as a set: both
  sides' additions are kept, both sides' removals apply. Other arrays are atomic.
- A value changed to different values on both sides (or changed on one side and removed
  on the other) is a conflict. Nothing is ever merged line by line.

``base`` may be :data:`MISSING` (no base known): every key both sides hold with
different values is then a conflict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


@dataclass
class MergeResult:
    """``value``: the merge (theirs at every conflicting path); ``conflicts``: those paths
    (``$.cards[id=7].hp``). Clean when ``conflicts`` is empty."""

    value: Any
    conflicts: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def same(a: Any, b: Any) -> bool:
    """JSON equality: ``true`` is not ``1``, ``1`` is ``1.0``, key order doesn't matter."""
    if a is b:
        return True
    if a is MISSING or b is MISSING:
        return False
    if _is_num(a) and _is_num(b):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def _id_list(v: Any) -> dict[Any, Any] | None:
    """``{id: element}`` when ``v`` is a list of objects with unique hashable ids."""
    if not isinstance(v, list):
        return None
    out: dict[Any, Any] = {}
    for el in v:
        if not isinstance(el, dict) or "id" not in el:
            return None
        key = el["id"]
        if isinstance(key, (dict, list)) or isinstance(key, bool) or key in out:
            return None
        out[key] = el
    return out


def _scalar_list(v: Any) -> bool:
    return isinstance(v, list) and all(not isinstance(el, (dict, list)) for el in v)


def merge(base: Any, theirs: Any, mine: Any, *, set_arrays: bool = False) -> MergeResult:
    """Merge ``mine`` into ``theirs`` on top of ``base``. See the module docstring."""
    conflicts: list[str] = []
    value = _merge(base, theirs, mine, "$", conflicts, set_arrays)
    return MergeResult(value, conflicts)


def _merge(base: Any, theirs: Any, mine: Any, path: str, conflicts: list[str], set_arrays: bool) -> Any:
    if same(theirs, mine) or same(mine, base):
        return theirs
    if same(theirs, base):
        return mine
    b_obj = base if isinstance(base, dict) else ({} if base is MISSING else None)
    if isinstance(theirs, dict) and isinstance(mine, dict) and b_obj is not None:
        return _merge_objects(b_obj, theirs, mine, path, conflicts, set_arrays)
    if isinstance(theirs, list) and isinstance(mine, list):
        b_list = base if isinstance(base, list) else ([] if base is MISSING else None)
        if b_list is not None:
            t_ids, m_ids, b_ids = _id_list(theirs), _id_list(mine), _id_list(b_list)
            if t_ids is not None and m_ids is not None and b_ids is not None:
                return _merge_id_lists(b_ids, theirs, t_ids, mine, m_ids, path, conflicts, set_arrays)
            if set_arrays and _scalar_list(theirs) and _scalar_list(mine) and _scalar_list(b_list):
                return _merge_sets(b_list, theirs, mine)
    conflicts.append(path)
    return theirs


def _merge_objects(base: dict, theirs: dict, mine: dict, path: str, conflicts: list[str], set_arrays: bool) -> dict:
    out: dict[str, Any] = {}
    order = list(theirs) + [k for k in mine if k not in theirs] + [k for k in base if k not in theirs and k not in mine]
    for k in order:
        merged = _merge(base.get(k, MISSING), theirs.get(k, MISSING), mine.get(k, MISSING), f"{path}.{k}",
                        conflicts, set_arrays)
        if merged is not MISSING:
            out[k] = merged
    return out


def _merge_id_lists(base: dict, theirs: list, t_ids: dict, mine: list, m_ids: dict, path: str,
                    conflicts: list[str], set_arrays: bool) -> list:
    out: list[Any] = []
    for el in theirs:
        key = el["id"]
        merged = _merge(base.get(key, MISSING), el, m_ids.get(key, MISSING), f"{path}[id={key}]", conflicts,
                        set_arrays)
        if merged is not MISSING:
            out.append(merged)
    for el in mine:
        key = el["id"]
        if key in t_ids:
            continue
        # Not in theirs: mine added it (kept), or theirs removed it (gone unless mine changed it).
        merged = _merge(base.get(key, MISSING), MISSING, el, f"{path}[id={key}]", conflicts, set_arrays)
        if merged is not MISSING:
            out.append(merged)
    return out


def _merge_sets(base: list, theirs: list, mine: list) -> list:
    def keyed(v: list) -> dict[Any, Any]:
        return {(type(x).__name__ if not _is_num(x) else "num", x): x for x in v}

    b, t, m = keyed(base), keyed(theirs), keyed(mine)
    removed = {k for k in b if k not in m}
    out = [x for k, x in t.items() if k not in removed]
    seen = set(t)
    out += [x for k, x in m.items() if k not in seen and k not in b]
    return out
