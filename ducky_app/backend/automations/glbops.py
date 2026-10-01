"""Free 3D tools that run on this PC on GLB files (plan §6, 3D): size and info, fit to a
box, set the origin, rotate, take the texture maps out, and put new ones on.

GLB is read and written directly (JSON chunk + binary chunk), so nothing extra is
installed. Moves, turns and scales wrap the scene in one new root node: the model's
own data, skin and animations are left as they are."""

from __future__ import annotations

import io
import json
import math
import struct
from pathlib import Path
from typing import Any

from backend.automations.files import file_ref, with_url
from backend.automations.media import path_of

_MAGIC = 0x46546C67  # "glTF"
_JSON = 0x4E4F534A
_BIN = 0x004E4942
_FLOAT = 5126
_ORIGIN_MODES = ("keep", "min", "center", "max", "mass")


# --------------------------------------------------------------------------- read / write


def read(path: str | Path) -> tuple[dict[str, Any], bytearray]:
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError(f"{Path(path).name} isn't a GLB file.")
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != _MAGIC:
        raise ValueError(f"{Path(path).name} isn't a GLB file.")
    if version != 2:
        raise ValueError(f"{Path(path).name} is glTF {version}; only glTF 2 is supported.")
    gltf: dict[str, Any] | None = None
    binary = bytearray()
    at = 12
    while at + 8 <= len(data):
        size, kind = struct.unpack_from("<II", data, at)
        chunk = data[at + 8:at + 8 + size]
        if kind == _JSON:
            gltf = json.loads(chunk.decode("utf-8"))
        elif kind == _BIN and not binary:
            binary = bytearray(chunk)
        at += 8 + size
    if gltf is None:
        raise ValueError(f"{Path(path).name} has no glTF data.")
    return gltf, binary


def write(gltf: dict[str, Any], binary: bytearray | bytes, path: str | Path) -> Path:
    if binary:
        gltf.setdefault("buffers", [{}])
        gltf["buffers"][0] = {**{k: v for k, v in gltf["buffers"][0].items() if k != "uri"}, "byteLength": len(binary)}
    doc = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    doc += b" " * (-len(doc) % 4)
    body = bytes(binary) + b"\0" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(doc), _JSON) + doc
    if body:
        chunks += struct.pack("<II", len(body), _BIN) + body
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(struct.pack("<III", _MAGIC, 2, 12 + len(chunks)) + chunks)
    return target


def _open(inputs: dict[str, Any]) -> tuple[dict[str, Any], bytearray, Path]:
    path = path_of(inputs.get("mesh"))
    if not path:
        raise ValueError("Nothing in 3D model: wire a model in or pick one in the details.")
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"3D model {source.name} isn't on this PC any more.")
    if source.suffix.lower() != ".glb":
        raise ValueError(f"{source.name} isn't a GLB. These tools work on GLB files; turn it into one with Convert 3D model first.")
    gltf, binary = read(source)
    return gltf, binary, source


def _save(gltf: dict[str, Any], binary: bytearray, folder: Path, source: Path) -> dict[str, Any]:
    target = write(gltf, binary, folder / f"{source.stem}.glb")
    return with_url(file_ref(target, "mesh"))


# --------------------------------------------------------------------------- math (column-major 4x4)


def _identity() -> list[float]:
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


def _trs(node: dict[str, Any]) -> list[float]:
    if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
        return [float(v) for v in node["matrix"]]
    tx, ty, tz = (node.get("translation") or [0, 0, 0])[:3]
    qx, qy, qz, qw = (node.get("rotation") or [0, 0, 0, 1])[:4]
    sx, sy, sz = (node.get("scale") or [1, 1, 1])[:3]
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz, wx, wy, wz = qx * qy, qx * qz, qy * qz, qw * qx, qw * qy, qw * qz
    return [
        (1 - 2 * (yy + zz)) * sx, 2 * (xy + wz) * sx, 2 * (xz - wy) * sx, 0,
        2 * (xy - wz) * sy, (1 - 2 * (xx + zz)) * sy, 2 * (yz + wx) * sy, 0,
        2 * (xz + wy) * sz, 2 * (yz - wx) * sz, (1 - 2 * (xx + yy)) * sz, 0,
        tx, ty, tz, 1,
    ]


def _apply(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14])


def _scene_roots(gltf: dict[str, Any]) -> list[int]:
    scenes = gltf.get("scenes") or []
    index = int(gltf.get("scene") or 0)
    if scenes and 0 <= index < len(scenes):
        return list(scenes[index].get("nodes") or [])
    children = {child for node in gltf.get("nodes") or [] for child in node.get("children") or []}
    return [i for i in range(len(gltf.get("nodes") or [])) if i not in children]


def _mesh_nodes(gltf: dict[str, Any]):
    """(node index, world matrix) for every node that draws a mesh."""
    nodes = gltf.get("nodes") or []
    stack = [(i, _identity()) for i in _scene_roots(gltf)]
    seen: set[int] = set()
    while stack:
        index, parent = stack.pop()
        if index in seen or not 0 <= index < len(nodes):
            continue
        seen.add(index)
        world = _mul(parent, _trs(nodes[index]))
        if nodes[index].get("mesh") is not None:
            yield index, world
        stack.extend((child, world) for child in nodes[index].get("children") or [])


def _positions(gltf: dict[str, Any], binary: bytearray, accessor_index: int) -> list[tuple[float, float, float]]:
    acc = (gltf.get("accessors") or [])[accessor_index]
    if acc.get("componentType") != _FLOAT or acc.get("type") != "VEC3" or acc.get("bufferView") is None:
        return []
    view = gltf["bufferViews"][acc["bufferView"]]
    start = int(view.get("byteOffset") or 0) + int(acc.get("byteOffset") or 0)
    stride = int(view.get("byteStride") or 12)
    return [struct.unpack_from("<fff", binary, start + i * stride) for i in range(int(acc.get("count") or 0))]


def bounds(gltf: dict[str, Any], binary: bytearray, *, points: bool = False):
    """World box (min, max) of everything drawn; with ``points`` also the vertex average."""
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    total, count = [0.0, 0.0, 0.0], 0
    meshes = gltf.get("meshes") or []
    for node_index, world in _mesh_nodes(gltf):
        mesh = meshes[gltf["nodes"][node_index]["mesh"]]
        for prim in mesh.get("primitives") or []:
            pos = (prim.get("attributes") or {}).get("POSITION")
            if pos is None:
                continue
            acc = gltf["accessors"][pos]
            if points:
                verts = _positions(gltf, binary, pos)
                for v in verts:
                    w = _apply(world, v)
                    for axis in range(3):
                        total[axis] += w[axis]
                count += len(verts)
            amin, amax = acc.get("min"), acc.get("max")
            if not (isinstance(amin, list) and isinstance(amax, list)):
                verts = _positions(gltf, binary, pos)
                if not verts:
                    continue
                amin = [min(v[i] for v in verts) for i in range(3)]
                amax = [max(v[i] for v in verts) for i in range(3)]
            for cx in (amin[0], amax[0]):
                for cy in (amin[1], amax[1]):
                    for cz in (amin[2], amax[2]):
                        w = _apply(world, (cx, cy, cz))
                        for axis in range(3):
                            lo[axis] = min(lo[axis], w[axis])
                            hi[axis] = max(hi[axis], w[axis])
    if lo[0] == math.inf:
        raise ValueError("That model has no geometry to measure.")
    mass = [t / count for t in total] if points and count else [(a + b) / 2 for a, b in zip(lo, hi)]
    return (lo, hi, mass) if points else (lo, hi)


def _wrap(gltf: dict[str, Any], *, translation=None, rotation=None, scale=None) -> None:
    """Put the scene under one new root that moves / turns / scales all of it."""
    roots = _scene_roots(gltf)
    node: dict[str, Any] = {"name": "Ducky transform", "children": roots}
    if translation:
        node["translation"] = [float(v) for v in translation]
    if rotation:
        node["rotation"] = [float(v) for v in rotation]
    if scale:
        node["scale"] = [float(v) for v in scale]
    gltf.setdefault("nodes", []).append(node)
    index = len(gltf["nodes"]) - 1
    scenes = gltf.setdefault("scenes", [{}])
    scene_index = int(gltf.get("scene") or 0)
    if not 0 <= scene_index < len(scenes):
        scene_index = 0
    scenes[scene_index]["nodes"] = [index]
    gltf["scene"] = scene_index


def _num(inputs: dict[str, Any], cfg: dict[str, Any], key: str) -> float | None:
    for raw in (inputs.get(key), cfg.get(key)):
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key.title()} must be a number, not {raw!r}.") from exc
    return None


# --------------------------------------------------------------------------- nodes


def info(_cfg: dict[str, Any], inputs: dict[str, Any], _folder: Path) -> dict[str, Any]:
    gltf, binary, _source = _open(inputs)
    lo, hi = bounds(gltf, binary)
    size = {"width": hi[0] - lo[0], "height": hi[1] - lo[1], "depth": hi[2] - lo[2]}
    triangles = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            ref = prim.get("indices", (prim.get("attributes") or {}).get("POSITION"))
            if ref is not None:
                triangles += int(gltf["accessors"][ref].get("count") or 0) // 3
    details = {
        **{k: round(v, 6) for k, v in size.items()},
        "triangles": triangles,
        "materials": len(gltf.get("materials") or []),
        "rigged": bool(gltf.get("skins")),
        "animations": len(gltf.get("animations") or []),
    }
    return {"ok": True, "outputs": {**{k: details[k] for k in ("width", "height", "depth", "triangles")}, "info": details}, "result": details}


def fit_box(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    gltf, binary, source = _open(inputs)
    lo, hi = bounds(gltf, binary)
    size = [hi[i] - lo[i] for i in range(3)]
    wanted = [_num(inputs, cfg, "width"), _num(inputs, cfg, "height"), _num(inputs, cfg, "depth")]
    if all(v is None for v in wanted):
        raise ValueError("Set a width, height or depth to fit into.")
    if any(v is not None and v <= 0 for v in wanted):
        raise ValueError("Sizes must be more than 0.")
    ratios = [wanted[i] / size[i] if wanted[i] is not None and size[i] > 0 else None for i in range(3)]
    if cfg.get("stretch") is True:
        scale = [r if r is not None else 1.0 for r in ratios]
    else:  # keep proportions: the tightest given side wins
        factor = min(r for r in ratios if r is not None)
        scale = [factor] * 3
    _wrap(gltf, scale=scale)
    new = [size[i] * scale[i] for i in range(3)]
    return {"ok": True, "outputs": {"mesh": _save(gltf, binary, folder, source)},
            "result": {"width": new[0], "height": new[1], "depth": new[2], "scale": scale}}


def set_origin(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    gltf, binary, source = _open(inputs)
    modes = []
    for axis in ("x", "y", "z"):
        mode = str(inputs.get(axis) or cfg.get(axis) or ("min" if axis == "y" else "center")).strip().lower()
        if mode not in _ORIGIN_MODES:
            raise ValueError(f"{axis.upper()} must be one of {', '.join(_ORIGIN_MODES)}.")
        modes.append(mode)
    if "mass" in modes:
        lo, hi, mass = bounds(gltf, binary, points=True)
    else:
        lo, hi = bounds(gltf, binary)
        mass = [(a + b) / 2 for a, b in zip(lo, hi)]
    pick = {"min": lo, "max": hi, "center": [(a + b) / 2 for a, b in zip(lo, hi)], "mass": mass}
    shift = [0.0 if modes[i] == "keep" else -pick[modes[i]][i] for i in range(3)]
    _wrap(gltf, translation=shift)
    return {"ok": True, "outputs": {"mesh": _save(gltf, binary, folder, source)}, "result": {"moved_by": shift, "x": modes[0], "y": modes[1], "z": modes[2]}}


def _quat(x_deg: float, y_deg: float, z_deg: float) -> list[float]:
    """Turn about X, then Y, then Z (degrees) as a quaternion [x, y, z, w]."""
    hx, hy, hz = (math.radians(v) / 2 for v in (x_deg, y_deg, z_deg))
    cx, sx, cy, sy, cz, sz = math.cos(hx), math.sin(hx), math.cos(hy), math.sin(hy), math.cos(hz), math.sin(hz)
    return [sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz, cx * cy * sz - sx * sy * cz, cx * cy * cz + sx * sy * sz]


def rotate(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    gltf, binary, source = _open(inputs)
    turns = [(_num(inputs, cfg, axis) or 0.0) for axis in ("x", "y", "z")]
    if not any(turns):
        raise ValueError("Set how many degrees to turn around X, Y or Z.")
    _wrap(gltf, rotation=_quat(*turns))
    return {"ok": True, "outputs": {"mesh": _save(gltf, binary, folder, source)}, "result": {"degrees": turns}}


# --------------------------------------------------------------------------- textures


_MAPS = ("base_color", "roughness", "metallic", "normal", "occlusion", "emissive")


def _image_bytes(gltf: dict[str, Any], binary: bytearray, texture_index: int | None, base: Path) -> bytes | None:
    if texture_index is None:
        return None
    textures = gltf.get("textures") or []
    if not 0 <= texture_index < len(textures):
        return None
    source = textures[texture_index].get("source")
    images = gltf.get("images") or []
    if source is None or not 0 <= source < len(images):
        return None
    image = images[source]
    if image.get("bufferView") is not None:
        view = gltf["bufferViews"][image["bufferView"]]
        start = int(view.get("byteOffset") or 0)
        return bytes(binary[start:start + int(view["byteLength"])])
    uri = str(image.get("uri") or "")
    if uri.startswith("data:"):
        import base64

        return base64.b64decode(uri.split(",", 1)[1])
    if uri and (base / uri).is_file():
        return (base / uri).read_bytes()
    return None


def extract_textures(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image

    gltf, binary, source = _open(inputs)
    materials = gltf.get("materials") or []
    if not materials:
        raise ValueError(f"{source.name} has no materials.")
    index = int(_num(inputs, cfg, "material") or 0)
    if not 0 <= index < len(materials):
        raise ValueError(f"{source.name} has {len(materials)} material(s); pick 0 to {len(materials) - 1}.")
    mat = materials[index]
    pbr = mat.get("pbrMetallicRoughness") or {}
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {name: None for name in _MAPS}

    def save(name: str, raw: bytes | None, channel: str = "") -> None:
        if not raw:
            return
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            picked = img.convert("RGB").getchannel(channel) if channel else img
            target = folder / f"{name}.png"
            picked.save(target, "PNG")
        out[name] = with_url(file_ref(target, "image"))

    tex = lambda slot: (slot or {}).get("index") if isinstance(slot, dict) else None  # noqa: E731
    save("base_color", _image_bytes(gltf, binary, tex(pbr.get("baseColorTexture")), source.parent))
    mr = _image_bytes(gltf, binary, tex(pbr.get("metallicRoughnessTexture")), source.parent)
    save("roughness", mr, "G")
    save("metallic", mr, "B")
    save("normal", _image_bytes(gltf, binary, tex(mat.get("normalTexture")), source.parent))
    save("occlusion", _image_bytes(gltf, binary, tex(mat.get("occlusionTexture")), source.parent), "R")
    save("emissive", _image_bytes(gltf, binary, tex(mat.get("emissiveTexture")), source.parent))
    found = [name for name in _MAPS if out[name]]
    if not found:
        raise ValueError(f"Material {index} of {source.name} has no texture maps.")
    return {"ok": True, "outputs": out, "result": {"material": mat.get("name") or index, "maps": found}}


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _add_image(gltf: dict[str, Any], binary: bytearray, png: bytes) -> int:
    binary.extend(b"\0" * (-len(binary) % 4))
    gltf.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(png)})
    binary.extend(png)
    gltf.setdefault("buffers", [{"byteLength": 0}])
    gltf.setdefault("images", []).append({"bufferView": len(gltf["bufferViews"]) - 1, "mimeType": "image/png"})
    gltf.setdefault("textures", []).append({"source": len(gltf["images"]) - 1})
    return len(gltf["textures"]) - 1


def apply_textures(_cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image

    gltf, binary, source = _open(inputs)

    def load(pin: str):
        path = path_of(inputs.get(pin))
        if not path:
            return None
        if not Path(path).is_file():
            raise ValueError(f"{pin.replace('_', ' ').title()} image {Path(path).name} isn't on this PC any more.")
        with Image.open(path) as img:
            img.load()
            return img.copy()

    maps = {name: load(name) for name in ("base_color", "roughness", "metallic", "normal", "occlusion")}
    if not any(maps.values()):
        raise ValueError("Wire at least one texture map in.")
    materials = gltf.setdefault("materials", [])
    if not materials:
        materials.append({"name": "Ducky material", "pbrMetallicRoughness": {}})
        for mesh in gltf.get("meshes") or []:
            for prim in mesh.get("primitives") or []:
                prim.setdefault("material", 0)
    slots: dict[str, int] = {}
    if maps["base_color"] is not None:
        slots["base"] = _add_image(gltf, binary, _png(maps["base_color"].convert("RGBA")))
    if maps["normal"] is not None:
        slots["normal"] = _add_image(gltf, binary, _png(maps["normal"].convert("RGB")))
    if maps["occlusion"] is not None:
        slots["occlusion"] = _add_image(gltf, binary, _png(maps["occlusion"].convert("L").convert("RGB")))
    if maps["roughness"] is not None or maps["metallic"] is not None:
        first = maps["roughness"] or maps["metallic"]
        size = first.size
        pbr0 = materials[0].get("pbrMetallicRoughness") or {}
        rough = maps["roughness"].convert("L").resize(size) if maps["roughness"] is not None else Image.new("L", size, round(255 * float(pbr0.get("roughnessFactor", 1.0))))
        metal = maps["metallic"].convert("L").resize(size) if maps["metallic"] is not None else Image.new("L", size, round(255 * float(pbr0.get("metallicFactor", 1.0))))
        slots["mr"] = _add_image(gltf, binary, _png(Image.merge("RGB", (Image.new("L", size, 255), rough, metal))))
    for mat in materials:
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        if "base" in slots:
            pbr["baseColorTexture"] = {"index": slots["base"]}
            pbr.pop("baseColorFactor", None)
        if "mr" in slots:
            pbr["metallicRoughnessTexture"] = {"index": slots["mr"]}
            pbr["roughnessFactor"] = 1.0
            pbr["metallicFactor"] = 1.0
        if "normal" in slots:
            mat["normalTexture"] = {"index": slots["normal"]}
        if "occlusion" in slots:
            mat["occlusionTexture"] = {"index": slots["occlusion"]}
    return {"ok": True, "outputs": {"mesh": _save(gltf, binary, folder, source)},
            "result": {"applied": [name for name, img in maps.items() if img is not None], "materials": len(materials)}}


OPS = {
    "mesh.info": info,
    "mesh.fit_box": fit_box,
    "mesh.set_origin": set_origin,
    "mesh.rotate": rotate,
    "mesh.textures_extract": extract_textures,
    "mesh.textures_apply": apply_textures,
}
