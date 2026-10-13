"""Let the editor give render memory back after off-screen work.

A viewport capture (Epic's ``EditorAppToolset.CaptureViewport``) allocates large
transient render targets. Unreal's render-target pool frees an element only after
it has gone unused for a few dozen *rendered* frames, and the pool is ticked only
while a viewport draws. Editor viewports are not realtime by default, so after a
capture nothing draws and the buffers stay pinned: measured +700-800 MB of process
memory per capture on a dense island, never returned on its own (a forced garbage
collection frees nothing — these are not UObjects). Redrawing the viewport ~60
times returned all of it (+36 MB left over).

So after a capture, and after a batch of heavy editor commands, the Slate tick asks
the level viewports to redraw once per tick for a short burst. Invalidation is a
plain redraw request: the user's realtime setting is never touched.
"""

from __future__ import annotations

import unreal

#: Redraws per burst. The pool keeps an element for ~30 unused frames; 60 draws
#: covers that with margin and costs about a second of normal viewport rendering.
TRIM_TICKS = 60

_remaining = 0


def request_trim(ticks: int = TRIM_TICKS) -> None:
    """Ask for a redraw burst. Overlapping requests extend, never stack."""
    global _remaining
    _remaining = max(_remaining, int(ticks))


def pending() -> int:
    return _remaining


def tick() -> None:
    """One redraw per editor tick while a burst is pending; silent when idle."""
    global _remaining
    if _remaining <= 0:
        return
    _remaining -= 1
    try:
        _invalidate_viewports()
    except Exception as exc:  # no level viewport (hub), editor closing
        _remaining = 0
        try:
            from listener.logutil import log_msg

            log_msg(f"Render trim stopped: {exc}", "warn")
        except Exception:
            pass


def _invalidate_viewports() -> None:
    sub = None
    try:
        sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    except Exception:
        sub = None
    if sub is not None and hasattr(sub, "editor_invalidate_viewports"):
        sub.editor_invalidate_viewports()
        return
    unreal.EditorLevelLibrary.editor_invalidate_viewports()
