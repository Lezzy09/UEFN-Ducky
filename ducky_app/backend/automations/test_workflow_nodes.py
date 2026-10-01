"""Every workflow node works: at least one test per node type in the catalog.

Paid generators (3D AI Studio, Meshy), UEFN, Blender and the models are faked at
their edge (the tool / completion call), so these prove what each node sends, what it
hands on and how it fails; the last test fails if a catalog node has no test here or
elsewhere."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from backend.automations import catalog, glbops, media, runner, store, templates
from backend.automations.files import media_url, resolve_media
from backend.automations.pins import check_wires


@pytest.fixture(autouse=True)
def files(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "use_db", lambda *_: False)
    monkeypatch.setattr(store, "_files_dir", lambda: tmp_path / "wf")
    (tmp_path / "wf").mkdir()
    monkeypatch.setattr(store, "_announce_graphs_changed", lambda: None)
    monkeypatch.setattr("frontend.ui_web.agent_modes.push_ui_event", lambda _e: None)


# --------------------------------------------------------------------------- helpers


def png(path: Path, size=(8, 8), color=(255, 0, 0, 255)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, "PNG")
    return str(path)


def ref(path: str, kind: str = "image", **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "path": str(path), "name": Path(path).name, **extra}


def run(ntype: str, config: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None, nid: str = "n") -> dict[str, Any]:
    return runner._exec_node({"id": nid, "type": ntype, "config": config or {}}, {}, inputs or {})


def _png_bytes(color) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return buf.getvalue()


def make_glb(path: Path, *, offset=(0.0, 0.0, 0.0), textured: bool = True) -> str:
    """One triangle 2 wide (X), 4 tall (Y), 1 deep (Z) with base color and metal/rough maps."""
    binary = bytearray(struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 4, 1))
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": list(offset)}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [2, 4, 1]}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36}],
        "materials": [{"pbrMetallicRoughness": {}}],
    }
    if textured:
        for color in ((255, 0, 0), (255, 128, 64)):
            data = _png_bytes(color)
            binary.extend(b"\0" * (-len(binary) % 4))
            gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
            binary.extend(data)
        gltf["images"] = [{"bufferView": 1, "mimeType": "image/png"}, {"bufferView": 2, "mimeType": "image/png"}]
        gltf["textures"] = [{"source": 0}, {"source": 1}]
        gltf["materials"][0]["pbrMetallicRoughness"] = {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 1}}
    return str(glbops.write(gltf, binary, path))


def make_text_pdf(path: Path, pages: list[str]) -> str:
    objects: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + len(pages) * 2
    for i, text in enumerate(pages):
        stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents {4 + i * 2} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return str(path)


# --------------------------------------------------------------------------- fakes


class Tools:
    """Stand-ins for the plugin tools: they record calls and download fake files."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.off: set[str] = set()
        self.fail: dict[str, str] = {}

    def __call__(self, name: str):
        if name in self.off:
            return None

        def fn(**kwargs: Any) -> str:
            self.calls.append((name, kwargs))
            if name in self.fail:
                return self.fail[name]
            if name == "import_asset":
                return json.dumps({"ok": True, "result": {"imported": [f"/Game/{kwargs['destination_path']}/{Path(kwargs['source_file']).stem}"],
                                                          "destination_path": f"/Game/{kwargs['destination_path']}"}})
            if name == "blender_execute_blender_code":
                code = kwargs["code"]
                target = re.search(r"OUT = '([^']+)'", code)
                if target and target.group(1).endswith(".png"):
                    png(Path(target.group(1)))
                elif target:
                    make_glb(Path(target.group(1)))
                return json.dumps({"ok": True, "result": {"objects": ["Mesh"]}})
            out = Path(kwargs.get("output_dir") or self.tmp / "dl")
            out.mkdir(parents=True, exist_ok=True)
            if name in ("studio3d_render",) or "image" in name and "to_3d" not in name or name in ("studio3d_remove_bg",):
                paths = [png(out / "result.png")]
            else:
                paths = [str(out / "model.fbx"), make_glb(out / "model.glb")]
                Path(paths[0]).write_bytes(b"fbx")
                if name == "meshy_convert":
                    (out / "model.usdz").write_bytes(b"usdz")
                    paths.append(str(out / "model.usdz"))
            return json.dumps({"task_id": f"task-{len(self.calls)}", "status": "SUCCEEDED", "finished": True, "downloaded": paths,
                               "model_urls": {"glb": "https://assets.example/model.glb"}})

        return fn


@pytest.fixture
def tools(monkeypatch, tmp_path):
    fake = Tools(tmp_path)
    monkeypatch.setattr(media, "tool_fn", fake)
    return fake


@pytest.fixture
def model(monkeypatch):
    """A model that answers with whatever the test sets; records each prompt."""
    seen: list[dict[str, Any]] = []
    answers: list[str] = []

    def complete(provider, prompt, model_id="", *, system="", images=None):
        seen.append({"prompt": prompt, "system": system, "images": list(images or []), "model": model_id})
        return {"ok": True, "text": answers.pop(0) if answers else "answer"}

    monkeypatch.setattr("backend.automations.llm_complete.complete_prompt", complete)
    monkeypatch.setattr(runner, "_model_choice", lambda cfg: ("openai", str(cfg.get("model") or "gpt-test")))
    monkeypatch.setattr("backend.agent.model_capabilities.model_in_cache", lambda *_: False)
    return {"seen": seen, "answers": answers}


# --------------------------------------------------------------------------- inputs


@pytest.mark.parametrize("ntype, value, expected", [
    ("input.text", "hi", {"text": "hi"}),
    ("input.number", "4.5", {"number": 4.5}),
    ("input.boolean", True, {"value": True}),
    ("input.json", '{"a": [1, 2]}', {"value": {"a": [1, 2]}}),
])
def test_value_inputs(ntype, value, expected):
    step = run(ntype, {"value": value})
    assert step["ok"] and step["outputs"] == expected


def test_json_input_says_what_is_wrong():
    step = run("input.json", {"value": "{nope"})
    assert step["ok"] is False and "isn't valid JSON" in step["error"]


@pytest.mark.parametrize("ntype, pin", [
    ("input.image", "image"), ("input.audio", "audio"), ("input.video", "video"), ("input.mesh", "mesh"),
    ("input.pdf", "pdf"), ("input.svg", "svg"), ("input.file", "file"),
])
def test_file_inputs_hand_on_one_file_ref(ntype, pin):
    step = run(ntype, {"value": {"path": "C:/x/thing.bin", "name": "thing.bin"}})
    assert step["ok"] and step["outputs"][pin]["path"] == "C:/x/thing.bin"


def test_images_input_hands_on_a_list():
    step = run("input.images", {"value": [{"path": "C:/a.png"}, "C:/b.png"]})
    assert [item["name"] for item in step["outputs"]["images"]] == ["a.png", "b.png"]


# --------------------------------------------------------------------------- links


def test_links_are_signed_and_only_for_media(tmp_path):
    picture = png(tmp_path / "duck.png")
    url = media_url(picture)
    sig, token = url.split("/workflow-media/")[1].split("/")[:2]
    assert resolve_media(sig, token) == Path(picture)
    with pytest.raises(ValueError):
        resolve_media("0" * 32, token)
    (tmp_path / "evil.exe").write_bytes(b"x")
    assert media_url(tmp_path / "evil.exe") == ""


# --------------------------------------------------------------------------- image generators


def test_paid_nodes_wait_for_the_spend_switch(tools):
    step = run("image.generate", {}, {"prompt": "a duck"})
    assert step["ok"] is False and "Spend credits" in step["error"] and "5 credits" in step["error"]
    assert tools.calls == []


def test_text_to_image_calls_the_picked_backend(tools):
    step = run("image.generate", {"spend": True, "backend": "seedream"}, {"prompt": "a duck"})
    assert step["ok"], step
    name, args = tools.calls[0]
    assert name == "studio3d_image_seedream" and args["prompt"] == "a duck"
    assert args["confirm_spend"] is True and args["wait"] is True and "workflow_media" in args["output_dir"]
    image = step["outputs"]["image"]
    assert image["kind"] == "image" and image["path"].endswith("result.png") and "/workflow-media/" in image["url"]
    assert step["result"]["credits"] == 10


def test_a_backend_whose_plugin_is_off_says_so(tools):
    tools.off.add("studio3d_image_gemini25flash")
    step = run("image.generate", {"spend": True}, {"prompt": "a duck"})
    assert step["ok"] is False and "3D AI Studio plugin" in step["error"]


def test_the_tools_own_error_comes_through(tools):
    tools.fail["studio3d_image_gemini25flash"] = "Error: 3D AI Studio: insufficient credits (402)."
    step = run("image.generate", {"spend": True}, {"prompt": "a duck"})
    assert step["ok"] is False and "insufficient credits" in step["error"]


def test_edit_image_sends_picture_and_prompt(tools, tmp_path):
    step = run("image.edit", {"spend": True}, {"image": ref(png(tmp_path / "in.png")), "prompt": "add a hat"})
    assert step["ok"], step
    name, args = tools.calls[0]
    assert name == "meshy_image_to_image" and args["prompt"] == "add a hat" and args["image"].endswith("in.png")


@pytest.mark.parametrize("ntype, tool", [("image.remove_bg", "studio3d_remove_bg"), ("image.upscale", "studio3d_image_enhance")])
def test_picture_cleanups(tools, tmp_path, ntype, tool):
    step = run(ntype, {"spend": True}, {"image": ref(png(tmp_path / "in.png"))})
    assert step["ok"] and tools.calls[0][0] == tool and step["outputs"]["image"]["kind"] == "image"


def test_a_missing_picture_is_named(tools):
    step = run("image.remove_bg", {"spend": True}, {"image": ref("C:/gone/duck.png")})
    assert step["ok"] is False and "duck.png isn't on this PC" in step["error"]


# --------------------------------------------------------------------------- 3D generators and cloud tools


def test_text_to_3d_hands_on_the_glb_with_its_task(tools):
    step = run("mesh.generate", {"spend": True}, {"prompt": "a chest"})
    assert step["ok"], step
    mesh = step["outputs"]["mesh"]
    assert mesh["path"].endswith("model.glb") and mesh["provider"] == "Meshy" and mesh["task_id"]
    assert mesh["remote"] == "https://assets.example/model.glb"
    assert len(step["outputs"]["files"]) == 2


def test_image_to_3d_falls_back_to_the_next_backend(tools, tmp_path):
    tools.fail["meshy_image_to_3d"] = "Error: Meshy is down"
    step = run("mesh.from_image", {"spend": True, "fallback": True}, {"image": ref(png(tmp_path / "in.png"))})
    assert step["ok"], step
    assert [c[0] for c in tools.calls] == ["meshy_image_to_3d", "studio3d_trellis"]
    assert "Meshy is down" in step["result"]["fell_back_after"][0]


def test_image_to_3d_without_fallback_stops(tools, tmp_path):
    tools.fail["meshy_image_to_3d"] = "Error: Meshy is down"
    step = run("mesh.from_image", {"spend": True}, {"image": ref(png(tmp_path / "in.png")), "prompt": "shiny"})
    assert step["ok"] is False and "Meshy is down" in step["error"]
    assert tools.calls[0][1]["texture_prompt"] == "shiny"


def test_multi_view_needs_two_pictures(tools, tmp_path):
    one = run("mesh.multi_view", {"spend": True}, {"images": [ref(png(tmp_path / "a.png"))]})
    assert one["ok"] is False and "at least 2" in one["error"]
    two = run("mesh.multi_view", {"spend": True}, {"images": [ref(png(tmp_path / "a.png")), ref(png(tmp_path / "b.png"))]})
    assert two["ok"], two
    assert len(json.loads(tools.calls[0][1]["images"])) == 2


def test_meshy_edits_reuse_the_task_or_send_the_file(tools, tmp_path):
    made = ref("C:/x/m.glb", "mesh", provider="Meshy", task_id="abc")
    assert run("mesh.remesh", {"spend": True}, {"mesh": made, "polycount": 5000})["ok"]
    assert tools.calls[-1][1]["input_task_id"] == "abc" and tools.calls[-1][1]["target_polycount"] == 5000
    local = make_glb(tmp_path / "mine.glb")
    assert run("mesh.uv_unwrap", {"spend": True}, {"mesh": ref(local, "mesh")})["ok"]
    assert tools.calls[-1][1]["model_url"].startswith("data:application/octet-stream;base64,")


def test_studio_tools_need_a_web_link(tools, tmp_path):
    local = ref(make_glb(tmp_path / "mine.glb"), "mesh")
    step = run("mesh.repair", {"spend": True}, {"mesh": local})
    assert step["ok"] is False and "web link" in step["error"]
    linked = {**local, "remote": "https://assets.example/m.glb"}
    assert run("mesh.repair", {"spend": True}, {"mesh": linked})["ok"]
    assert tools.calls[-1] == ("studio3d_repair", {**tools.calls[-1][1], "model_url": "https://assets.example/m.glb"})
    assert run("mesh.remesh", {"spend": True, "backend": "studio3d_optimize"}, {"mesh": linked})["ok"]
    assert tools.calls[-1][0] == "studio3d_optimize"


def test_retexture_takes_a_style_prompt_or_picture(tools, tmp_path):
    made = ref("C:/x/m.glb", "mesh", provider="Meshy", task_id="abc")
    assert run("mesh.retexture", {"spend": True}, {"mesh": made})["ok"] is False
    assert run("mesh.retexture", {"spend": True}, {"mesh": made, "prompt": "gold"})["ok"]
    assert tools.calls[-1][1]["text_style_prompt"] == "gold"
    assert run("mesh.retexture", {"spend": True}, {"mesh": made, "style_image": ref(png(tmp_path / "s.png"))})["ok"]
    assert tools.calls[-1][1]["image_style"].endswith("s.png")


def test_convert_hands_on_the_asked_format(tools):
    made = ref("C:/x/m.glb", "mesh", provider="Meshy", task_id="abc")
    step = run("mesh.convert", {"spend": True, "format": "usdz"}, {"mesh": made})
    assert step["ok"] and step["outputs"]["mesh"]["path"].endswith(".usdz")
    assert tools.calls[-1][1]["target_formats"] == "usdz"
    studio = run("mesh.convert", {"spend": True, "format": "usdz", "backend": "studio3d_convert"}, {"mesh": {**made, "remote": "https://a/m.glb"}})
    assert studio["ok"] is False and "obj, fbx" not in studio["error"] and "fbx, obj, stl, ply" in studio["error"]


def test_bake_and_render(tools):
    high = ref("C:/x/h.glb", "mesh", remote="https://a/h.glb")
    low = ref("C:/x/l.glb", "mesh", remote="https://a/l.glb")
    assert run("mesh.bake", {"spend": True}, {"high": high, "low": low})["ok"]
    assert tools.calls[-1][1] == {**tools.calls[-1][1], "high_poly_url": "https://a/h.glb", "low_poly_url": "https://a/l.glb"}
    shot = run("mesh.render", {"spend": True}, {"mesh": high})
    assert shot["ok"] and shot["outputs"]["image"]["kind"] == "image"


def test_rig_then_animate_several(tools):
    made = ref("C:/x/m.glb", "mesh", provider="Meshy", task_id="abc")
    rigged = run("mesh.rig", {"spend": True}, {"mesh": made, "height": 1.8})
    assert rigged["ok"] and rigged["outputs"]["mesh"]["stage"] == "rig"
    assert tools.calls[-1][1]["height_meters"] == 1.8
    anim = run("mesh.animate", {"spend": True, "actions": "11, 28 59"}, {"mesh": rigged["outputs"]["mesh"]})
    assert anim["ok"], anim
    assert [c[1]["action_id"] for c in tools.calls[-3:]] == [11, 28, 59]
    assert len(anim["outputs"]["meshes"]) == 3 and anim["result"]["credits"] == 9


def test_animate_checks_what_it_gets(tools):
    assert "Rig node" in run("mesh.animate", {"spend": True, "actions": "11"}, {"mesh": ref("C:/x/m.glb", "mesh")})["error"]
    rigged = ref("C:/x/m.glb", "mesh", provider="Meshy", task_id="r", stage="rig")
    assert "Rig node" in run("mesh.animate", {"spend": True, "actions": "-1"}, {"mesh": rigged})["error"]
    assert "Ten" in run("mesh.animate", {"spend": True, "actions": " ".join(str(n) for n in range(1, 12))}, {"mesh": rigged})["error"]


# --------------------------------------------------------------------------- image tools (Pillow)


def _img(step, pin="image"):
    with Image.open(step["outputs"][pin]["path"]) as img:
        img.load()
        return img.copy()


@pytest.mark.parametrize("mode, size", [("fit", (50, 25)), ("fill", (50, 50)), ("stretch", (50, 50))])
def test_resize(tmp_path, mode, size):
    picture = ref(png(tmp_path / "in.png", (100, 50)))
    step = run("image.resize", {"mode": mode}, {"image": picture, "width": 50, "height": 50})
    assert step["ok"], step
    assert _img(step).size == size


def test_crop(tmp_path):
    picture = ref(png(tmp_path / "in.png", (100, 50)))
    assert _img(run("image.crop", {}, {"image": picture, "x": 10, "y": 5, "width": 20, "height": 10})).size == (20, 10)
    assert "outside" in run("image.crop", {}, {"image": picture, "x": 200})["error"]


def test_convert(tmp_path):
    step = run("image.convert", {"format": "jpg", "quality": 80}, {"image": ref(png(tmp_path / "in.png"))})
    assert step["outputs"]["image"]["path"].endswith(".jpg") and _img(step).mode == "RGB"


def test_alpha_split_and_combine(tmp_path):
    picture = ref(png(tmp_path / "in.png", color=(10, 20, 30, 128)))
    split = run("image.split_alpha", {}, {"image": picture})
    assert _img(split, "alpha").getpixel((0, 0)) == 128 and _img(split, "color").getpixel((0, 0)) == (10, 20, 30)
    joined = run("image.combine_alpha", {}, {"color": split["outputs"]["color"], "alpha": split["outputs"]["alpha"]})
    assert _img(joined).getpixel((0, 0)) == (10, 20, 30, 128)


def test_channels_split_and_combine(tmp_path):
    split = run("image.split_channels", {}, {"image": ref(png(tmp_path / "in.png", color=(10, 20, 30, 40)))})
    assert [_img(split, c).getpixel((0, 0)) for c in ("red", "green", "blue", "alpha")] == [10, 20, 30, 40]
    packed = run("image.combine_channels", {}, {"red": split["outputs"]["blue"], "green": split["outputs"]["red"]})
    assert _img(packed).getpixel((0, 0)) == (30, 10, 0, 255)
    assert run("image.combine_channels", {}, {})["ok"] is False


def test_combine_images(tmp_path):
    pictures = [ref(png(tmp_path / f"{n}.png", (10, 20))) for n in range(4)]
    assert _img(run("image.concat", {"direction": "row", "gap": 2}, {"images": pictures})).size == (46, 20)
    assert _img(run("image.concat", {"direction": "grid"}, {"images": pictures})).size == (20, 40)
    assert run("image.concat", {}, {"images": []})["ok"] is False


def test_text_to_picture(tmp_path):
    step = run("image.text", {"width": 300, "height": 100, "size": 30, "color": "#ffcc00"}, {"text": "Duck"})
    img = _img(step)
    assert img.size == (300, 100) and img.getbbox() is not None  # something was drawn
    assert "isn't a color" in run("image.text", {"color": "notacolor"}, {"text": "x"})["error"]


# --------------------------------------------------------------------------- 3D tools (GLB)


def test_mesh_info(tmp_path):
    step = run("mesh.info", {}, {"mesh": ref(make_glb(tmp_path / "m.glb"), "mesh")})
    assert step["ok"], step
    assert step["outputs"]["info"] == {**step["outputs"]["info"], "width": 2, "height": 4, "depth": 1, "triangles": 1, "materials": 1, "rigged": False}


def _box(step):
    gltf, binary = glbops.read(step["outputs"]["mesh"]["path"])
    return glbops.bounds(gltf, binary)


def test_fit_box_keeps_proportions_or_stretches(tmp_path):
    mesh = ref(make_glb(tmp_path / "m.glb"), "mesh")
    lo, hi = _box(run("mesh.fit_box", {}, {"mesh": mesh, "height": 2}))
    assert [round(hi[i] - lo[i], 6) for i in range(3)] == [1, 2, 0.5]
    lo, hi = _box(run("mesh.fit_box", {"stretch": True}, {"mesh": mesh, "width": 4, "height": 2}))
    assert [round(hi[i] - lo[i], 6) for i in range(3)] == [4, 2, 1]
    assert "Set a width" in run("mesh.fit_box", {}, {"mesh": mesh})["error"]


def test_set_origin(tmp_path):
    mesh = ref(make_glb(tmp_path / "m.glb", offset=(5, 5, 5)), "mesh")
    lo, hi = _box(run("mesh.set_origin", {"x": "center", "y": "min", "z": "max"}, {"mesh": mesh}))
    assert [round(v, 6) for v in lo] == [-1, 0, -1] and [round(v, 6) for v in hi] == [1, 4, 0]
    assert "must be one of" in run("mesh.set_origin", {"x": "middle"}, {"mesh": mesh})["error"]


def test_rotate(tmp_path):
    mesh = ref(make_glb(tmp_path / "m.glb"), "mesh")
    lo, hi = _box(run("mesh.rotate", {}, {"mesh": mesh, "z": 90}))
    assert [round(hi[i] - lo[i], 6) for i in range(3)] == [4, 2, 1]  # width and height swap
    assert "how many degrees" in run("mesh.rotate", {}, {"mesh": mesh})["error"]


def test_textures_out_and_back_in(tmp_path):
    mesh = ref(make_glb(tmp_path / "m.glb"), "mesh")
    out = run("mesh.textures_extract", {}, {"mesh": mesh})
    assert out["ok"], out
    assert _img(out, "base_color").convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert _img(out, "roughness").getpixel((0, 0)) == 128 and _img(out, "metallic").getpixel((0, 0)) == 64
    assert out["outputs"]["normal"] is None
    blue = ref(png(tmp_path / "blue.png", color=(0, 0, 255, 255)))
    applied = run("mesh.textures_apply", {}, {"mesh": mesh, "base_color": blue, "roughness": out["outputs"]["metallic"]})
    assert applied["ok"], applied
    again = run("mesh.textures_extract", {}, {"mesh": applied["outputs"]["mesh"]}, nid="again")
    assert _img(again, "base_color").convert("RGB").getpixel((0, 0)) == (0, 0, 255)
    assert _img(again, "roughness").getpixel((0, 0)) == 64


def test_3d_tools_need_a_glb(tmp_path):
    fbx = tmp_path / "m.fbx"
    fbx.write_bytes(b"x")
    assert "isn't a GLB" in run("mesh.info", {}, {"mesh": ref(str(fbx), "mesh")})["error"]
    assert "no texture" in run("mesh.textures_extract", {}, {"mesh": ref(make_glb(tmp_path / "plain.glb", textured=False), "mesh")})["error"]


def test_text_to_origin(model, tmp_path):
    model["answers"].append('Sure: {"x": "center", "y": "min", "z": "center"}')
    step = run("mesh.origin_text", {}, {"mesh": ref(make_glb(tmp_path / "m.glb", offset=(3, 3, 3)), "mesh"), "instruction": "bottom centre"})
    assert step["ok"], step
    assert step["result"]["y"] == "min" and "bottom centre" in model["seen"][0]["prompt"]
    lo, _hi = _box(step)
    assert round(lo[1], 6) == 0


# --------------------------------------------------------------------------- Blender, UEFN, save


def test_blender_nodes(tools, tmp_path):
    mesh = ref(make_glb(tmp_path / "m.glb"), "mesh")
    assert run("blender.open", {}, {"mesh": mesh})["ok"]
    assert "import_scene.gltf" in tools.calls[-1][1]["code"]
    shot = run("blender.render", {"transparent": True}, {"mesh": mesh, "size": 512})
    assert shot["ok"] and shot["outputs"]["image"]["path"].endswith("render.png")
    assert "W, H = 512, 512" in tools.calls[-1][1]["code"]
    exported = run("blender.export", {"selected": True}, {})
    assert exported["ok"] and exported["outputs"]["mesh"]["path"].endswith("scene.glb")
    assert "use_selection=True" in tools.calls[-1][1]["code"]
    tools.off.add("blender_execute_blender_code")
    assert "Blender plugin" in run("blender.export", {}, {})["error"]


def test_send_to_uefn_one_or_many(tools, tmp_path):
    one = run("uefn.import", {"folder": "Ducky/Props"}, {"file": ref(make_glb(tmp_path / "chest.glb"), "mesh")})
    assert one["ok"] and one["outputs"]["asset"] == "/Game/Ducky/Props/chest"
    many = run("uefn.import", {}, {"file": [ref(png(tmp_path / "a.png")), ref(png(tmp_path / "b.png"))]})
    assert many["outputs"]["assets"] == ["/Game/Ducky/a", "/Game/Ducky/b"]
    assert "files on this PC" in run("uefn.import", {}, {"file": "https://x/a.glb"})["error"]
    tools.off.add("import_asset")
    assert "UEFN plugin" in run("uefn.import", {}, {"file": ref(png(tmp_path / "a.png"))})["error"]


def test_save_file_keeps_both(tmp_path):
    picture = ref(png(tmp_path / "duck.png"))
    dest = tmp_path / "out"
    first = run("util.save_file", {"folder": str(dest)}, {"file": picture})
    second = run("util.save_file", {"folder": str(dest)}, {"file": picture})
    assert Path(first["outputs"]["path"]).name == "duck.png" and Path(second["outputs"]["path"]).name == "duck (2).png"
    named = run("util.save_file", {"folder": str(dest), "name": "hero", "overwrite": True}, {"file": picture})
    assert Path(named["outputs"]["path"]).name == "hero.png"
    assert "Choose the folder" in run("util.save_file", {}, {"file": picture})["error"]


@pytest.mark.parametrize("ntype, target, ok", [
    ("uefn.close", "frontend.window_view.close_uefn", True),
    ("uefn.wait_window", "backend.tools.core.uefn_windows.wait_uefn_window", False),
])
def test_uefn_window_steps(monkeypatch, ntype, target, ok):
    monkeypatch.setattr(target, lambda *a, **k: {"ok": ok, **({} if ok else {"error": "no window"})})
    step = run(ntype, {"title_regex": "Unreal"})
    assert step["ok"] is ok and (ok or step["error"] == "no window")


# --------------------------------------------------------------------------- lists


def test_list_nodes():
    assert run("list.make", {"names": ["a", "b", "c"]}, {"a": 1, "b": None, "c": "x"})["outputs"]["list"] == [1, "x"]
    assert run("list.get", {}, {"list": [1, 2, 3], "index": -1})["outputs"]["item"] == 3
    assert "no item 5" in run("list.get", {}, {"list": [1], "index": 5})["error"]
    assert run("list.count", {}, {"list": "[1, 2]"})["outputs"]["count"] == 2
    assert run("list.join", {"separator": "\\n"}, {"list": ["a", "b"]})["outputs"]["text"] == "a\nb"
    kept = run("list.filter", {"expression": "item > 1 && index < 3"}, {"list": [1, 2, 3, 4]})
    assert kept["outputs"] == {"list": [2, 3], "count": 2}
    assert run("list.map", {"expression": "item * 10"}, {"list": [1, 2]})["outputs"]["list"] == [10, 20]
    assert "Write the expression" in run("list.map", {}, {"list": [1]})["error"]


# --------------------------------------------------------------------------- documents


def test_pdf_text_and_pages(tmp_path):
    pdf = ref(make_text_pdf(tmp_path / "doc.pdf", ["Hello duck", "Second page"]), "pdf")
    everything = run("pdf.text", {}, {"pdf": pdf})
    assert everything["ok"], everything
    assert "Hello duck" in everything["outputs"]["text"] and "Second page" in everything["outputs"]["text"]
    second = run("pdf.text", {"pages": "2"}, {"pdf": pdf})
    assert second["outputs"]["page_texts"] == ["Second page"]
    assert "should look like" in run("pdf.text", {"pages": "two"}, {"pdf": pdf})["error"]


def test_pdf_images(tmp_path):
    doc = tmp_path / "pics.pdf"
    Image.new("RGB", (40, 30), (0, 200, 0)).save(doc, "PDF")
    step = run("pdf.images", {}, {"pdf": ref(str(doc), "pdf")})
    assert step["ok"], step
    assert step["outputs"]["count"] == 1 and _img({"outputs": {"image": step["outputs"]["images"][0]}}).size == (40, 30)


# --------------------------------------------------------------------------- model nodes


def test_ask_about_an_image(model, tmp_path):
    picture = ref(png(tmp_path / "duck.png"))
    step = run("llm.vision", {"system": "Be short."}, {"image": [picture], "prompt": "What is it?"})
    assert step["ok"] and step["outputs"]["text"] == "answer"
    assert model["seen"][0]["images"] == [picture["path"]] and model["seen"][0]["system"] == "Be short."
    assert "Nothing in Image" in run("llm.vision", {}, {})["error"]


def test_extract_data_fills_each_field(model):
    model["answers"].append('```json\n{"name": "Duck Knight", "level": 12}\n```')
    step = run("llm.extract", {"names": ["name", "level", "rarity"]}, {"text": "Duck Knight, level 12"})
    assert step["ok"], step
    assert step["outputs"] == {"data": {"name": "Duck Knight", "level": 12, "rarity": None}, "name": "Duck Knight", "level": 12, "rarity": None}
    model["answers"].append("no json here")
    assert "wasn't JSON" in run("llm.extract", {"names": ["a"]}, {"text": "x"})["error"]


def test_translate(model):
    step = run("llm.translate", {"language": "German"}, {"text": "Hello"})
    assert step["ok"] and "into German" in model["seen"][0]["prompt"]


def test_find_by_description(model):
    model["answers"].append("[2, 0, 9]")
    items = [{"kind": "image", "path": "C:/duck.png", "name": "duck.png"}, "a cat", "a duck pond"]
    step = run("llm.pick", {}, {"list": items, "prompt": "ducks"})
    assert step["outputs"] == {"list": ["a duck pond", items[0]], "item": "a duck pond", "count": 2}
    assert "0. duck.png" in model["seen"][0]["prompt"]


# --------------------------------------------------------------------------- pipelines, run one node, catalog


def _save(graph: dict[str, Any], name: str = "Pipe") -> str:
    return str(store.save_workflow({"name": name, "graph": graph})["id"])


def _with_spend(graph: dict[str, Any]) -> dict[str, Any]:
    for node in graph["nodes"]:
        if node["type"] in media.BACKENDS:
            node["config"]["spend"] = True
    return graph


def test_prompt_to_picture_to_3d_to_uefn_runs_from_the_template(tools):
    row = next(t for t in templates.list_templates() if t["id"] == "builtin:pipe-prompt-image-3d")
    out = runner.run_workflow(_save(_with_spend(row["graph"])))
    assert out["ok"], out
    assert [c[0] for c in tools.calls] == ["studio3d_image_gemini25flash", "studio3d_remove_bg", "meshy_image_to_3d", "import_asset"]
    assert out["node_outputs"]["p"]["value"].startswith("/Game/Ducky/Props/")


def test_character_pipeline_imports_every_animation(tools):
    row = next(t for t in templates.list_templates() if t["id"] == "builtin:pipe-character-full")
    out = runner.run_workflow(_save(_with_spend(row["graph"])))
    assert out["ok"], out
    names = [c[0] for c in tools.calls]
    assert names[:5] == ["studio3d_image_gemini25flash", "studio3d_remove_bg", "meshy_image_to_3d", "meshy_rig", "meshy_animate"]
    assert names.count("meshy_animate") == 3 and names.count("import_asset") == 3
    assert len(out["node_outputs"]["p"]["value"]) == 3


def test_run_one_node_reuses_what_fed_it(tools):
    graph = {"nodes": [{"id": "q", "type": "input.text", "x": 0, "y": 0, "config": {"value": "a duck"}},
                       {"id": "gen", "type": "image.generate", "x": 300, "y": 0, "config": {"spend": True}},
                       {"id": "cut", "type": "image.remove_bg", "x": 600, "y": 0, "config": {"spend": True}}],
             "edges": [{"source": "q", "target": "gen", "kind": "data", "source_pin": "text", "target_pin": "prompt"},
                       {"source": "gen", "target": "cut", "kind": "data", "source_pin": "image", "target_pin": "image"}]}
    wid = _save(graph)
    assert runner.run_workflow(wid)["ok"]
    assert [c[0] for c in tools.calls] == ["studio3d_image_gemini25flash", "studio3d_remove_bg"]
    again = runner.run_node(wid, "cut")
    assert again["ok"], again
    assert [c[0] for c in tools.calls] == ["studio3d_image_gemini25flash", "studio3d_remove_bg", "studio3d_remove_bg"]  # no new picture
    assert "cut" in again["node_outputs"] and runner.run_node(wid, "nope")["ok"] is False


def test_every_template_is_wired_right():
    specs = catalog.node_specs()
    rows = templates.list_templates()
    assert {t["category"] for t in rows} >= {"Images", "3D", "Characters", "Text & AI", "Documents", "Play tests", "UEFN"}
    for row in rows:
        graph = row["graph"]
        assert all(n["type"] in specs for n in graph["nodes"]), row["id"]
        assert check_wires(graph, specs) == [], row["id"]
    pipes = {t["id"]: t for t in rows}
    assert pipes["builtin:pipe-character-full"]["requires_plugins"] == ["studio3d", "meshy", "uefn"]
    assert pipes["builtin:pipe-sprite-sheet"]["requires_plugins"] == []


def test_paid_nodes_list_their_backends(tools):
    tools.off.add("studio3d_tripo")
    rows = {n["type"]: n for n in catalog.list_nodes()}
    tripo = next(b for b in rows["mesh.generate"]["backends"] if b["id"] == "tripo")
    assert tripo["available"] is False and "3D AI Studio" in tripo["reason"] and tripo["credits"] == 60
    assert all(b["available"] for b in rows["image.generate"]["backends"])
    assert {f["id"] for f in rows["mesh.generate"]["config_fields"]} >= {"backend", "spend"}


def test_every_catalog_node_has_a_test():
    """A new node type must come with a test that names it."""
    here = Path(__file__).parent
    text = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in here.rglob("test_*.py"))
    text += "".join(p.read_text(encoding="utf-8", errors="ignore") for p in (here.parent / "tools").rglob("test_*.py"))
    missing = sorted(t for t in catalog.node_specs() if f'"{t}"' not in text and f"'{t}'" not in text)
    assert missing == []
