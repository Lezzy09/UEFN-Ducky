"""Image and 3D nodes (plan §7): each node type has a table of backends — a tool an
installed plugin registers (3D AI Studio, Meshy) or a core one — and the node calls
the one picked in its details, waits for it, and turns the files it downloads into
file refs on its output pins.

Paid backends keep the plugins' spend lock: a node only spends credits when its
"Spend credits" switch is on (a person turns it on; an AI asks them first)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

from backend.automations.files import file_ref, is_file_ref, kind_of, with_url

Args = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

STUDIO = "3D AI Studio"
MESHY = "Meshy"
_MAX_INLINE_MODEL = 25 * 1024 * 1024
# Main file when a generator downloads several (a model in many formats, textures…).
_PREFERRED = {
    "image": (".png", ".webp", ".jpg", ".jpeg"),
    "mesh": (".glb", ".fbx", ".obj", ".usdz", ".gltf", ".stl"),
}


# --------------------------------------------------------------------------- inputs


def path_of(value: Any) -> str:
    """A local path or URL from a wired value (a file ref, a list's first item, text)."""
    if isinstance(value, list):
        return path_of(value[0]) if value else ""
    if isinstance(value, dict):
        return str(value.get("path") or value.get("url") or "")
    return str(value or "").strip()


def _need_file(inputs: dict[str, Any], pin: str, what: str) -> str:
    path = path_of(inputs.get(pin))
    if not path:
        raise ValueError(f"Nothing in {what}: wire one in or pick it in the details.")
    if not path.lower().startswith(("http://", "https://", "data:")) and not Path(path).is_file():
        raise ValueError(f"{what} {Path(path).name} isn't on this PC any more.")
    return path


def _need_text(inputs: dict[str, Any], pin: str, what: str) -> str:
    raw = inputs.get(pin)
    text = (raw if isinstance(raw, str) else json.dumps(raw) if isinstance(raw, (dict, list)) else str(raw if raw is not None else "")).strip()
    if not text:
        raise ValueError(f"Nothing in {what}: wire text in or type it in the details.")
    return text


def _number(inputs: dict[str, Any], cfg: dict[str, Any], key: str, default: float) -> float:
    for raw in (inputs.get(key), cfg.get(key)):
        try:
            if raw not in (None, ""):
                return float(raw)
        except (TypeError, ValueError):
            continue
    return default


def _model_source(inputs: dict[str, Any]) -> dict[str, str]:
    """How a Meshy edit finds the model: the Meshy task that made it, else its link,
    else the file itself (sent inline)."""
    ref = inputs.get("mesh")
    if isinstance(ref, dict) and ref.get("provider") == MESHY and ref.get("task_id"):
        return {"input_task_id": str(ref["task_id"])}
    if isinstance(ref, dict) and str(ref.get("remote") or "").startswith("https://"):
        return {"model_url": str(ref["remote"])}
    path = _need_file(inputs, "mesh", "3D model")
    if path.lower().startswith(("http://", "https://", "data:")):
        return {"model_url": path}
    data = Path(path).read_bytes()
    if len(data) > _MAX_INLINE_MODEL:
        raise ValueError(f"{Path(path).name} is over 25 MB; Meshy can only edit models it made or smaller files.")
    return {"model_url": "data:application/octet-stream;base64," + base64.b64encode(data).decode("ascii")}


def _prompt(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {"prompt": _need_text(inputs, "prompt", "Prompt")}


def _image(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {"image": _need_file(inputs, "image", "Image")}


def _image_and_prompt(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {"image": _need_file(inputs, "image", "Image"), "prompt": _need_text(inputs, "prompt", "Prompt")}


def _meshy_image(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {"prompt": _need_text(inputs, "prompt", "Prompt"), "ai_model": "nano-banana"}


def _meshy_from_image(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {"image": _need_file(inputs, "image", "Image")}
    hint = inputs.get("prompt")
    if isinstance(hint, str) and hint.strip():
        args["texture_prompt"] = hint.strip()
    return args


def _remesh(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {**_model_source(inputs), "target_polycount": int(_number(inputs, cfg, "polycount", 30000)),
            "topology": "quad" if str(cfg.get("topology") or "") == "quad" else "triangle"}


def _retexture(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {**_model_source(inputs), "text_style_prompt": _need_text(inputs, "prompt", "Style")}


def _rig(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {**_model_source(inputs), "height_meters": _number(inputs, cfg, "height", 1.7)}


def _animate(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    ref = inputs.get("mesh")
    if not (isinstance(ref, dict) and ref.get("provider") == MESHY and ref.get("stage") == "rig" and ref.get("task_id")):
        raise ValueError("Animate needs the model straight from a Rig node (Meshy).")
    action = int(_number(inputs, cfg, "action_id", 0))
    if not action:
        raise ValueError("Set the animation number in the details (the Meshy animation library lists them).")
    return {"rig_task_id": str(ref["task_id"]), "action_id": action}


def _studio(tool: str, label: str, credits: int, args: Args, bid: str = "") -> dict[str, Any]:
    return {"id": bid or tool.removeprefix("studio3d_"), "label": label, "plugin": STUDIO, "tool": tool, "credits": credits, "args": args}


def _meshy(tool: str, label: str, credits: int, args: Args, bid: str = "", stage: str = "") -> dict[str, Any]:
    row = {"id": bid or tool, "label": label, "plugin": MESHY, "tool": tool, "credits": credits, "args": args}
    return {**row, "stage": stage} if stage else row


# node type → backends, first = default. Credits are the plugins' own estimates.
BACKENDS: dict[str, list[dict[str, Any]]] = {
    "image.generate": [
        _studio("studio3d_image_gemini25flash", "Gemini 2.5 Flash Image", 5, _prompt),
        _studio("studio3d_image_gemini31flash", "Gemini 3.1 Flash Image", 7, _prompt),
        _studio("studio3d_image_gemini3pro", "Gemini 3 Pro Image", 10, _prompt),
        _studio("studio3d_image_seedream", "SeeDream v5 Lite", 10, _prompt),
        _meshy("meshy_text_to_image", "Meshy · Nano Banana", 5, _meshy_image),
    ],
    "image.edit": [
        _meshy("meshy_image_to_image", "Meshy · Nano Banana", 5, lambda i, c: {**_image_and_prompt(i, c), "ai_model": "nano-banana"}),
    ],
    "image.remove_bg": [_studio("studio3d_remove_bg", "3D AI Studio", 5, _image, "studio3d")],
    "image.upscale": [_studio("studio3d_image_enhance", "3D AI Studio", 20, _image, "studio3d")],
    "mesh.generate": [
        _meshy("meshy_text_to_3d", "Meshy", 25, _prompt),
        _studio("studio3d_tripo", "Tripo v3", 60, _prompt),
        _studio("studio3d_tencent_rapid", "Hunyuan Rapid", 35, _prompt),
        _studio("studio3d_tencent_pro", "Hunyuan Pro", 80, _prompt),
        _studio("studio3d_tripo_p1", "Tripo P1", 100, _prompt),
    ],
    "mesh.from_image": [
        _meshy("meshy_image_to_3d", "Meshy", 25, _meshy_from_image),
        _studio("studio3d_trellis", "TRELLIS.2", 30, _image),
        _studio("studio3d_tripo", "Tripo v3", 60, _image),
        _studio("studio3d_tencent_rapid", "Hunyuan Rapid", 35, _image),
        _studio("studio3d_tencent_pro", "Hunyuan Pro", 80, _image),
    ],
    "mesh.remesh": [_meshy("meshy_remesh", "Meshy", 5, _remesh)],
    "mesh.retexture": [_meshy("meshy_retexture", "Meshy", 10, _retexture)],
    "mesh.rig": [_meshy("meshy_rig", "Meshy", 5, _rig, stage="rig")],
    "mesh.animate": [_meshy("meshy_animate", "Meshy", 3, _animate, stage="animate")],
}
# What each node's main output pin is called and what kind of file it carries.
OUTPUT: dict[str, tuple[str, str]] = {
    "image.generate": ("image", "image"),
    "image.edit": ("image", "image"),
    "image.remove_bg": ("image", "image"),
    "image.upscale": ("image", "image"),
    "mesh.generate": ("mesh", "mesh"),
    "mesh.from_image": ("mesh", "mesh"),
    "mesh.remesh": ("mesh", "mesh"),
    "mesh.retexture": ("mesh", "mesh"),
    "mesh.rig": ("mesh", "mesh"),
    "mesh.animate": ("mesh", "mesh"),
}


# --------------------------------------------------------------------------- tools


def tool_fn(name: str) -> Callable[..., Any] | None:
    """The function behind a registered tool, or None when its plugin is off."""
    try:
        from backend.server import mcp

        tool = mcp._tool_manager.get_tool(name)
    except Exception:
        return None
    return getattr(tool, "fn", None) if tool is not None else None


def backends_for(ntype: str) -> list[dict[str, Any]]:
    """The node's backends for its details dropdown: cost and whether each can run here."""
    out: list[dict[str, Any]] = []
    for row in BACKENDS.get(ntype, []):
        ready = tool_fn(row["tool"]) is not None
        out.append({
            "id": row["id"], "label": row["label"], "plugin": row["plugin"], "credits": row["credits"], "available": ready,
            **({} if ready else {"reason": f"Turn on the {row['plugin']} plugin in the Store and add its API key."}),
        })
    return out


def pick_backend(ntype: str, wanted: Any) -> dict[str, Any]:
    table = BACKENDS.get(ntype) or []
    if not table:
        raise ValueError(f"No backends for {ntype}.")
    return next((row for row in table if row["id"] == str(wanted or "")), table[0])


def _parse(raw: Any) -> dict[str, Any]:
    """A plugin tool's answer: JSON text, or text starting with "Error"."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.lower().startswith("error"):
        raise RuntimeError(text.split(":", 1)[1].strip() if ":" in text[:12] else text)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(text[:300] or "The tool sent nothing back.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The tool sent back something unexpected.")
    return data


def _main_file(paths: list[str], kind: str) -> str:
    for ext in _PREFERRED.get(kind, ()):
        for path in paths:
            if path.lower().endswith(ext):
                return path
    same = [path for path in paths if kind_of(path) == kind]
    return (same or paths)[0]


def _remote(data: dict[str, Any], kind: str) -> str:
    """The generator's own link to the main file (Meshy edits take it as model_url)."""
    if kind == "mesh":
        urls = data.get("model_urls") if isinstance(data.get("model_urls"), dict) else {}
        for fmt in ("glb", "fbx", "obj"):
            if str(urls.get(fmt) or "").startswith("https://"):
                return str(urls[fmt])
    for item in data.get("results") or []:
        url = item.get("asset") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith("https://") and kind_of(url.split("?")[0], "") == kind:
            return url
    return ""


def run_media(ntype: str, cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    """Run one image / 3D node on the backend picked in its details."""
    backend = pick_backend(ntype, cfg.get("backend"))
    credits = int(backend.get("credits") or 0)
    if credits > 0 and cfg.get("spend") is not True:
        return {"ok": False, "error": f"{backend['label']} costs about {credits} credits a run. Turn on Spend credits in this node's details to let it run."}
    fn = tool_fn(backend["tool"])
    if fn is None:
        return {"ok": False, "error": f"{backend['label']} needs the {backend['plugin']} plugin: turn it on in the Store and add its API key."}
    try:
        args = backend["args"](inputs, cfg)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    args.update({"wait": True, "output_dir": str(folder), **({"confirm_spend": True} if credits > 0 else {})})
    try:
        data = _parse(fn(**args))
    except RuntimeError as exc:
        return {"ok": False, "error": f"{backend['label']}: {exc}"}
    if data.get("failed") or str(data.get("status") or "").upper() in ("FAILED", "CANCELED", "CANCELLED"):
        reason = data.get("failure_reason") or data.get("error") or data.get("status")
        return {"ok": False, "error": f"{backend['label']} failed: {reason}"}
    paths = [str(p) for p in data.get("downloaded") or [] if p]
    pin, kind = OUTPUT[ntype]
    if not paths:
        return {"ok": False, "error": f"{backend['label']} finished but sent no files back."}
    main = _main_file(paths, kind)
    ref: dict[str, Any] = {**file_ref(main, kind), "provider": backend["plugin"], "backend": backend["id"]}
    if data.get("task_id"):
        ref["task_id"] = str(data["task_id"])
    if backend.get("stage"):
        ref["stage"] = backend["stage"]
    remote = _remote(data, kind)
    if remote:
        ref["remote"] = remote
    files = [with_url({**file_ref(path, kind_of(path)), **({"task_id": ref.get("task_id")} if ref.get("task_id") else {})}) for path in paths]
    return {
        "ok": True,
        "outputs": {pin: with_url(ref), "files": files},
        "result": {"backend": backend["label"], "credits": credits, "files": [f["path"] for f in files]},
    }


# --------------------------------------------------------------------------- send on


def send_to_uefn(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Import a file into the open UEFN project's Content Browser (needs UEFN running)."""
    try:
        path = _need_file(inputs, "file", "File")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if path.lower().startswith(("http://", "https://", "data:")):
        return {"ok": False, "error": "Send to UEFN takes a file on this PC; wire a generator's file or pick one."}
    fn = tool_fn("import_asset")
    if fn is None:
        return {"ok": False, "error": "UEFN tools are off: turn on the UEFN plugin."}
    folder = str(inputs.get("folder") or cfg.get("folder") or "").strip() or "Ducky"
    try:
        data = _parse(fn(source_file=path, destination_path=folder, replace_existing=cfg.get("replace") is not False))
    except RuntimeError as exc:
        return {"ok": False, "error": f"UEFN didn't take it: {exc}"}
    if data.get("ok") is False or data.get("error"):
        return {"ok": False, "error": f"UEFN didn't take it: {data.get('error') or data}"}
    body = data.get("result") if isinstance(data.get("result"), dict) else data
    imported = [str(item) for item in body.get("imported") or [] if item]
    if "imported" in body and not imported:
        return {"ok": False, "error": f"UEFN imported nothing from {Path(path).name}; check its format."}
    where = str(body.get("destination_path") or folder)
    return {"ok": True, "outputs": {"asset": imported[0] if imported else f"{where}/{Path(path).stem}"}, "result": body}


_BLENDER = (("meshy_import_to_blender", MESHY), ("studio3d_import_glb_to_blender", STUDIO))


def open_in_blender(_cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Open a model in the running Blender (through Meshy's or 3D AI Studio's importer)."""
    try:
        path = _need_file(inputs, "mesh", "3D model")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    for tool, _plugin in _BLENDER:
        fn = tool_fn(tool)
        if fn is None:
            continue
        try:
            data = _parse(fn(url_or_path=path))
        except RuntimeError as exc:
            return {"ok": False, "error": f"Blender didn't open it: {exc}"}
        return {"ok": True, "outputs": {"mesh": inputs.get("mesh")}, "result": data}
    return {"ok": False, "error": "Open in Blender needs the Meshy or 3D AI Studio plugin turned on, and Blender open with its MCP add-on."}


def refs_with_urls(value: Any, depth: int = 0) -> Any:
    """Every file ref inside a value gets a fresh link (run outputs, saved picks)."""
    if depth > 4:
        return value
    if is_file_ref(value):
        return with_url(value)
    if isinstance(value, list):
        return [refs_with_urls(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: refs_with_urls(item, depth + 1) for key, item in value.items()}
    return value
