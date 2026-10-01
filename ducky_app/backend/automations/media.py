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
    style = path_of(inputs.get("style_image"))
    hint = inputs.get("prompt")
    if not style and not (isinstance(hint, str) and hint.strip()):
        raise ValueError("Nothing in Style: type a style prompt or wire a style picture in.")
    args: dict[str, Any] = _model_source(inputs)
    if isinstance(hint, str) and hint.strip():
        args["text_style_prompt"] = hint.strip()
    if style:
        args["image_style"] = _need_file(inputs, "style_image", "Style image")
    return args


def _rig(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {**_model_source(inputs), "height_meters": _number(inputs, cfg, "height", 1.7)}


def action_ids(inputs: dict[str, Any], cfg: dict[str, Any]) -> list[int]:
    """The animations to make: '12, 35 101' or a list → [12, 35, 101] (at most 10)."""
    raw = inputs.get("actions")
    if raw in (None, "", []):
        raw = cfg.get("actions") if cfg.get("actions") not in (None, "") else cfg.get("action_id")
    items = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    out: list[int] = []
    for item in items:
        try:
            value = int(float(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Animations are numbers from the Meshy library, not {item!r}.") from exc
        if value <= 0:
            raise ValueError("Walking and running come with the Rig node; animations here are numbers from 1 up (Idle 1 is 11).")
        if value not in out:
            out.append(value)
    if not out:
        raise ValueError("Set the animation numbers in the details (the Meshy animation library lists them).")
    if len(out) > 10:
        raise ValueError("Ten animations at most per node.")
    return out


def _animate(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    ref = inputs.get("mesh")
    if not (isinstance(ref, dict) and ref.get("provider") == MESHY and ref.get("stage") == "rig" and ref.get("task_id")):
        raise ValueError("Animate needs the model straight from a Rig node (Meshy).")
    return {"rig_task_id": str(ref["task_id"]), "action_id": action_ids(inputs, cfg)[0]}


def _web_link(inputs: dict[str, Any], pin: str = "mesh", what: str = "3D model") -> str:
    """A web link to the model: 3D AI Studio's tools only take links, not files."""
    ref = inputs.get(pin)
    if isinstance(ref, dict) and str(ref.get("remote") or "").startswith("https://"):
        return str(ref["remote"])
    path = path_of(ref)
    if path.lower().startswith("https://"):
        return path
    if not path:
        raise ValueError(f"Nothing in {what}: wire a model in.")
    raise ValueError(f"3D AI Studio needs a model one of the 3D generators made (it has a web link); {Path(path).name} is only on this PC. Use the Meshy backend for local files.")


def _studio_model(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {"model_url": _web_link(inputs)}


def _multi_view(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    raw = inputs.get("images")
    paths = [path_of(item) for item in (raw if isinstance(raw, list) else [raw]) if path_of(item)]
    if len(paths) < 2:
        raise ValueError("Multi-view needs at least 2 pictures of the same thing (front, side, back…).")
    for path in paths:
        if not path.lower().startswith(("http://", "https://")) and not Path(path).is_file():
            raise ValueError(f"{Path(path).name} isn't on this PC any more.")
    return {"images": json.dumps(paths[:4])}


def _convert_meshy(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {**_model_source(inputs), "target_formats": _format(cfg, ("fbx", "glb", "obj", "usdz", "stl"))}


def _convert_studio(inputs: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {"model_url": _web_link(inputs), "output_format": _format(cfg, ("fbx", "obj", "stl", "ply"))}


def _format(cfg: dict[str, Any], allowed: tuple[str, ...]) -> str:
    fmt = str(cfg.get("format") or "fbx").strip().lower()
    if fmt not in allowed:
        raise ValueError(f"This backend makes {', '.join(allowed)}; pick one of those or another backend.")
    return fmt


def _bake(inputs: dict[str, Any], _cfg: dict[str, Any]) -> dict[str, Any]:
    return {"high_poly_url": _web_link(inputs, "high", "High-poly model"), "low_poly_url": _web_link(inputs, "low", "Low-poly model")}


def _studio(tool: str, label: str, credits: int, args: Args, bid: str = "") -> dict[str, Any]:
    return {"id": bid or tool.removeprefix("studio3d_image_").removeprefix("studio3d_"), "label": label, "plugin": STUDIO, "tool": tool, "credits": credits, "args": args}


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
    "mesh.multi_view": [_meshy("meshy_multi_image_to_3d", "Meshy", 25, _multi_view)],
    "mesh.remesh": [
        _meshy("meshy_remesh", "Meshy remesh", 5, _remesh),
        _studio("studio3d_optimize", "3D AI Studio optimize", 10, _studio_model, "studio3d_optimize"),
    ],
    "mesh.uv_unwrap": [_meshy("meshy_uv_unwrap", "Meshy", 5, lambda i, c: _model_source(i))],
    "mesh.convert": [
        _meshy("meshy_convert", "Meshy", 1, _convert_meshy),
        _studio("studio3d_convert", "3D AI Studio", 10, _convert_studio, "studio3d_convert"),
    ],
    "mesh.render": [_studio("studio3d_render", "3D AI Studio", 15, _studio_model, "studio3d")],
    "mesh.repair": [_studio("studio3d_repair", "3D AI Studio", 75, _studio_model, "studio3d")],
    "mesh.bake": [_studio("studio3d_bake_texture", "3D AI Studio", 5, _bake, "studio3d")],
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
    "mesh.multi_view": ("mesh", "mesh"),
    "mesh.uv_unwrap": ("mesh", "mesh"),
    "mesh.convert": ("mesh", "mesh"),
    "mesh.render": ("image", "image"),
    "mesh.repair": ("mesh", "mesh"),
    "mesh.bake": ("mesh", "mesh"),
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
    """Run one image / 3D node on the backend picked in its details. With "Try the
    next backend if it fails" on, a failure moves on to the next one that is set up."""
    first = pick_backend(ntype, cfg.get("backend"))
    if ntype == "mesh.animate":
        return _run_animations(cfg, inputs, folder)
    if cfg.get("fallback") is not True:
        return _run_once(ntype, first, cfg, inputs, folder)
    order = [first] + [row for row in BACKENDS.get(ntype, []) if row is not first]
    errors: list[str] = []
    for backend in order:
        if backend is not first and tool_fn(backend["tool"]) is None:
            continue
        step = _run_once(ntype, backend, cfg, inputs, folder)
        if step.get("ok"):
            if errors:
                step["result"] = {**step.get("result", {}), "fell_back_after": errors}
            return step
        if step.get("gate"):  # spend switch off or nothing wired: another backend won't help
            return step
        errors.append(str(step.get("error") or "failed"))
    return {"ok": False, "error": "Every backend failed: " + " · ".join(errors)}


def _run_animations(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    try:
        actions = action_ids(inputs, cfg)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "gate": True}
    backend = pick_backend("mesh.animate", "")
    meshes: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for n, action in enumerate(actions):
        step = _run_once("mesh.animate", backend, cfg, {**inputs, "actions": [action]}, folder / f"{n + 1}-{action}", credits_for=len(actions))
        if not step.get("ok"):
            return step if not meshes else {**step, "error": f"Animation {action}: {step.get('error')}"}
        meshes.append(step["outputs"]["mesh"])
        files.extend(step["outputs"]["files"])
    return {"ok": True, "outputs": {"mesh": meshes[0], "meshes": meshes, "files": files},
            "result": {"backend": backend["label"], "animations": actions, "credits": int(backend["credits"]) * len(actions)}}


def _run_once(ntype: str, backend: dict[str, Any], cfg: dict[str, Any], inputs: dict[str, Any], folder: Path, *, credits_for: int = 1) -> dict[str, Any]:
    credits = int(backend.get("credits") or 0)
    if credits > 0 and cfg.get("spend") is not True:
        return {"ok": False, "gate": True, "error": f"{backend['label']} costs about {credits * credits_for} credits a run. Turn on Spend credits in this node's details to let it run."}
    fn = tool_fn(backend["tool"])
    if fn is None:
        return {"ok": False, "error": f"{backend['label']} needs the {backend['plugin']} plugin: turn it on in the Store and add its API key."}
    try:
        args = backend["args"](inputs, cfg)
    except (ValueError, OSError) as exc:
        return {"ok": False, "gate": True, "error": str(exc)}
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
    wanted = str(cfg.get("format") or "").lower() if ntype == "mesh.convert" else ""
    main = next((path for path in paths if wanted and path.lower().endswith("." + wanted)), "") or _main_file(paths, kind)
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
    """Import files into the open UEFN project's Content Browser (needs UEFN running).
    A list (every animation, every picture) imports each one."""
    raw = inputs.get("file")
    items = [item for item in (raw if isinstance(raw, list) else [raw]) if path_of(item)]
    if not items:
        return {"ok": False, "error": "Nothing in File: wire a model, picture or sound in."}
    fn = tool_fn("import_asset")
    if fn is None:
        return {"ok": False, "error": "UEFN tools are off: turn on the UEFN plugin."}
    folder = str(inputs.get("folder") or cfg.get("folder") or "").strip() or "Ducky"
    assets: list[str] = []
    for item in items[:50]:
        path = path_of(item)
        if path.lower().startswith(("http://", "https://", "data:")):
            return {"ok": False, "error": "Send to UEFN takes files on this PC; wire a generator's file or pick one."}
        if not Path(path).is_file():
            return {"ok": False, "error": f"{Path(path).name} isn't on this PC any more."}
        try:
            data = _parse(fn(source_file=path, destination_path=folder, replace_existing=cfg.get("replace") is not False))
        except RuntimeError as exc:
            return {"ok": False, "error": f"UEFN didn't take {Path(path).name}: {exc}"}
        if data.get("ok") is False or data.get("error"):
            return {"ok": False, "error": f"UEFN didn't take {Path(path).name}: {data.get('error') or data}"}
        body = data.get("result") if isinstance(data.get("result"), dict) else data
        imported = [str(entry) for entry in body.get("imported") or [] if entry]
        if "imported" in body and not imported:
            return {"ok": False, "error": f"UEFN imported nothing from {Path(path).name}; check its format."}
        where = str(body.get("destination_path") or folder)
        assets.extend(imported or [f"{where}/{Path(path).stem}"])
    return {"ok": True, "outputs": {"asset": assets[0], "assets": assets}, "result": {"imported": assets, "folder": folder}}


_IMPORT_CODE = """
import bpy
SRC = {src!r}
ext = SRC.lower().rsplit(".", 1)[-1]
old = set(bpy.data.objects)
if ext in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=SRC)
elif ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=SRC)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=SRC)
elif ext == "stl":
    bpy.ops.wm.stl_import(filepath=SRC)
else:
    raise ValueError("Blender opens GLB, FBX, OBJ or STL here")
result = {{"objects": [o.name for o in bpy.data.objects if o not in old]}}
"""


def open_in_blender(_cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Import a model into the Blender that is open (Blender plugin + its MCP add-on)."""
    try:
        path = _need_file(inputs, "mesh", "3D model")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = _blender(_IMPORT_CODE.format(src=path))
    except RuntimeError as exc:
        return {"ok": False, "error": f"Blender: {exc}"}
    return {"ok": True, "outputs": {"mesh": inputs.get("mesh")}, "result": result}


_RENDER_CODE = """
import bpy, math
from mathutils import Vector
SRC = {src!r}
OUT = {out!r}
W, H = {width}, {height}
before_scene = bpy.context.window_manager.windows[0].scene if bpy.context.window_manager.windows else bpy.context.scene
scene = bpy.data.scenes.new("Ducky render")
win = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
if win:
    win.scene = scene
old = set(bpy.data.objects)
ext = SRC.lower().rsplit(".", 1)[-1]
if ext in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=SRC)
elif ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=SRC)
elif ext == "obj":
    bpy.ops.wm.obj_import(filepath=SRC)
else:
    raise ValueError("Blender render takes GLB, FBX or OBJ")
made = [o for o in bpy.data.objects if o not in old]
for o in made:
    if o.name not in scene.collection.all_objects:
        scene.collection.objects.link(o)
pts = [o.matrix_world @ Vector(c) for o in made if o.type == "MESH" for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 0.01)
cam = bpy.data.objects.new("Ducky camera", bpy.data.cameras.new("Ducky camera"))
scene.collection.objects.link(cam)
cam.location = center + Vector((1.0, -1.4, 0.8)).normalized() * radius * 3.2
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
sun = bpy.data.objects.new("Ducky light", bpy.data.lights.new("Ducky light", "SUN"))
sun.rotation_euler = (math.radians(50), 0, math.radians(30))
scene.collection.objects.link(sun)
world = bpy.data.worlds.new("Ducky world")
world.color = (0.05, 0.05, 0.05)
scene.world = world
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.film_transparent = {transparent}
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True, scene=scene.name)
for o in made + [cam, sun]:
    bpy.data.objects.remove(o, do_unlink=True)
if win:
    win.scene = before_scene
bpy.data.scenes.remove(scene)
result = {{"image": OUT, "objects": len(made)}}
"""

_EXPORT_CODE = """
import bpy
OUT = {out!r}
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection={selected})
result = {{"mesh": OUT}}
"""


def _blender(code: str) -> dict[str, Any]:
    fn = tool_fn("blender_execute_blender_code")
    if fn is None:
        raise RuntimeError("Turn on the Blender plugin and open Blender with its MCP add-on.")
    data = _parse(fn(code=code))
    if data.get("ok") is False or data.get("error"):
        raise RuntimeError(str(data.get("error") or data.get("stderr") or "Blender didn't run it."))
    return data.get("result") if isinstance(data.get("result"), dict) else {}


def blender_render(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    """Render a model in the running Blender (its own temporary scene) to a PNG."""
    try:
        path = _need_file(inputs, "mesh", "3D model")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    folder.mkdir(parents=True, exist_ok=True)
    out = str(folder / "render.png")
    size = int(_number(inputs, cfg, "size", 1024))
    code = _RENDER_CODE.format(src=path, out=out, width=size, height=size, transparent=cfg.get("transparent") is not False)
    try:
        _blender(code)
    except RuntimeError as exc:
        return {"ok": False, "error": f"Blender: {exc}"}
    if not Path(out).is_file():
        return {"ok": False, "error": "Blender finished but wrote no picture."}
    return {"ok": True, "outputs": {"image": with_url(file_ref(out, "image"))}}


def blender_export(cfg: dict[str, Any], _inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    """Save what is open in Blender (or just the selection) as a GLB for other 3D nodes."""
    folder.mkdir(parents=True, exist_ok=True)
    out = str(folder / "scene.glb")
    try:
        _blender(_EXPORT_CODE.format(out=out, selected=cfg.get("selected") is True))
    except RuntimeError as exc:
        return {"ok": False, "error": f"Blender: {exc}"}
    if not Path(out).is_file():
        return {"ok": False, "error": "Blender finished but wrote no GLB."}
    return {"ok": True, "outputs": {"mesh": with_url(file_ref(out, "mesh"))}}


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


def refresh_links(wf: dict[str, Any]) -> dict[str, Any]:
    """Links for every file a workflow shows: picked files and what its runs made."""
    for node in (wf.get("graph") or {}).get("nodes") or []:
        cfg = node.get("config") if isinstance(node, dict) else None
        if isinstance(cfg, dict):
            for key in ("value", "inputs"):
                if key in cfg:
                    cfg[key] = refs_with_urls(cfg[key])
    for run in wf.get("runs") or []:
        if isinstance(run, dict) and isinstance(run.get("node_outputs"), dict):
            run["node_outputs"] = refs_with_urls(run["node_outputs"])
    return wf
