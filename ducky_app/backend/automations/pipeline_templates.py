"""Ready-made pipelines in the New workflow picker, by category (plan §10): pictures,
3D models, characters (prompt → picture → 3D → rig → animations → UEFN), text and
documents. Paid steps ship with Spend credits off; the run says which switch to turn on."""

from __future__ import annotations

from typing import Any

CATEGORY_ORDER = ("Images", "3D", "Characters", "Text & AI", "Documents", "Play tests", "UEFN")


def _n(nid: str, ntype: str, left: int, top: int, label: str = "", inputs: dict[str, Any] | None = None, **config: Any) -> dict[str, Any]:
    node: dict[str, Any] = {"id": nid, "type": ntype, "x": left, "y": top, "config": dict(config)}
    if inputs:
        node["config"]["inputs"] = dict(inputs)
    if label:
        node["label"] = label
    return node


def _w(source: str, source_pin: str, target: str, target_pin: str) -> dict[str, Any]:
    return {"source": source, "target": target, "kind": "data", "source_pin": source_pin, "target_pin": target_pin}


def _t(tid: str, name: str, icon: str, category: str, description: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    row = {"id": f"builtin:{tid}", "name": name, "label": name, "icon": icon, "category": category,
           "description": description, "kind": "builtin", "graph": {"nodes": nodes, "edges": edges}}
    # Its Text to Image steps were made for 3D AI Studio's Gemini, a backend that plugin
    # declares: with the plugin off it isn't in the list, so the template names it here.
    if any(n["type"] == "image.generate" and n["config"].get("backend") in _STUDIO_IMAGES for n in nodes):
        row["requires_plugins"] = ["studio3d"]
    return row


_STUDIO_IMAGES = {"gemini25flash", "gemini31flash", "gemini3pro", "seedream"}


_COL = 300
_PAID = " Turn on Spend credits on the paid steps before the first run."

PIPELINE_TEMPLATES: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ Images
    _t("pipe-prompt-image", "Prompt to picture", "🖼️", "Images",
       "Type a prompt, get a picture (Gemini by default; pick another backend in its details)." + _PAID,
       [_n("q", "input.text", 0, 0, "Prompt", value="A cute cartoon duck wearing a knight helmet, game asset, plain background"),
        _n("gen", "image.generate", _COL, 0, backend="gemini25flash"),
        _n("p", "util.preview", _COL * 2, 0, "Picture")],
       [_w("q", "text", "gen", "prompt"), _w("gen", "image", "p", "value")]),
    _t("pipe-prompt-cutout", "Prompt to cut-out picture", "✂️", "Images",
       "A picture from your prompt with the background removed, ready for UI, cards or Image to 3D." + _PAID,
       [_n("q", "input.text", 0, 0, "Prompt", value="A golden trophy with a duck on top, game icon, plain background"),
        _n("gen", "image.generate", _COL, 0, backend="gemini25flash"),
        _n("cut", "image.remove_bg", _COL * 2, 0),
        _n("p", "util.preview", _COL * 3, 0, "Cut-out")],
       [_w("q", "text", "gen", "prompt"), _w("gen", "image", "cut", "image"), _w("cut", "image", "p", "value")]),
    _t("pipe-upscale", "Upscale a picture", "🔍", "Images",
       "Pick a picture; get it bigger and sharper." + _PAID,
       [_n("img", "input.image", 0, 0, "Picture"), _n("up", "image.upscale", _COL, 0), _n("p", "util.preview", _COL * 2, 0, "Upscaled")],
       [_w("img", "image", "up", "image"), _w("up", "image", "p", "value")]),
    _t("pipe-sprite-sheet", "Sprite sheet from pictures", "🧩", "Images",
       "Pick several pictures; they are laid out in a grid as one sheet. Free, runs on this PC.",
       [_n("imgs", "input.images", 0, 0, "Pictures"), _n("sheet", "image.concat", _COL, 0, direction="grid", gap=8),
        _n("p", "util.preview", _COL * 2, 0, "Sheet")],
       [_w("imgs", "images", "sheet", "images"), _w("sheet", "image", "p", "value")]),
    _t("pipe-title-card", "Title card", "🔤", "Images",
       "Text drawn onto a 1920×1080 picture for loading screens and signs. Free, runs on this PC.",
       [_n("q", "input.text", 0, 0, "Title", value="WELCOME TO DUCK ISLAND"),
        _n("card", "image.text", _COL, 0, size=120, width=1920, height=1080, color="#ffd23f", background="#101820"),
        _n("p", "util.preview", _COL * 2, 0, "Card")],
       [_w("q", "text", "card", "text"), _w("card", "image", "p", "value")]),
    _t("pipe-orm", "Pack an ORM texture", "🎨", "Images",
       "Occlusion, roughness and metallic maps packed into one texture (red, green, blue) the way UEFN materials read them. Free.",
       [_n("ao", "input.image", 0, 0, "Occlusion"), _n("rough", "input.image", 0, 160, "Roughness"), _n("metal", "input.image", 0, 320, "Metallic"),
        _n("pack", "image.combine_channels", _COL, 120), _n("p", "util.preview", _COL * 2, 120, "ORM")],
       [_w("ao", "image", "pack", "red"), _w("rough", "image", "pack", "green"), _w("metal", "image", "pack", "blue"), _w("pack", "image", "p", "value")]),
    # ------------------------------------------------------------------ 3D
    _t("pipe-prompt-3d-uefn", "Prompt to 3D model in UEFN", "🧊", "3D",
       "Prompt → textured 3D model (Meshy) → origin at the bottom center → imported into your open UEFN project." + _PAID,
       [_n("q", "input.text", 0, 0, "Prompt", value="A stylized treasure chest, game-ready prop"),
        _n("m", "mesh.generate", _COL, 0, backend="meshy_text_to_3d"),
        _n("o", "mesh.set_origin", _COL * 2, 0, x="center", y="min", z="center"),
        _n("u", "uefn.import", _COL * 3, 0, folder="Ducky/Props"),
        _n("p", "util.preview", _COL * 4, 0, "In UEFN")],
       [_w("q", "text", "m", "prompt"), _w("m", "mesh", "o", "mesh"), _w("o", "mesh", "u", "file"), _w("u", "asset", "p", "value")]),
    _t("pipe-image-3d-uefn", "Picture to 3D model in UEFN", "📸", "3D",
       "One picture → 3D model (tries the next backend if one fails) → origin at the bottom → into UEFN." + _PAID,
       [_n("img", "input.image", 0, 0, "Picture"),
        _n("m", "mesh.from_image", _COL, 0, backend="meshy_image_to_3d", fallback=True),
        _n("o", "mesh.set_origin", _COL * 2, 0, x="center", y="min", z="center"),
        _n("u", "uefn.import", _COL * 3, 0, folder="Ducky/Props"),
        _n("p", "util.preview", _COL * 4, 0, "In UEFN")],
       [_w("img", "image", "m", "image"), _w("m", "mesh", "o", "mesh"), _w("o", "mesh", "u", "file"), _w("u", "asset", "p", "value")]),
    _t("pipe-prompt-image-3d", "Prompt → picture → 3D → UEFN", "🚀", "3D",
       "The full prop pipeline: a picture from your prompt, background removed, turned into a 3D model and imported into UEFN." + _PAID,
       [_n("q", "input.text", 0, 0, "Prompt", value="A wooden barrel with iron bands, stylized game prop, plain background"),
        _n("gen", "image.generate", _COL, 0, backend="gemini25flash"),
        _n("cut", "image.remove_bg", _COL * 2, 0),
        _n("m", "mesh.from_image", _COL * 3, 0, backend="meshy_image_to_3d", fallback=True),
        _n("u", "uefn.import", _COL * 4, 0, folder="Ducky/Props"),
        _n("p", "util.preview", _COL * 5, 0, "In UEFN")],
       [_w("q", "text", "gen", "prompt"), _w("gen", "image", "cut", "image"), _w("cut", "image", "m", "image"),
        _w("m", "mesh", "u", "file"), _w("u", "asset", "p", "value")]),
    _t("pipe-game-ready", "Make a model game-ready", "🛠️", "3D",
       "Pick a model: fewer polygons, scaled to 1 m tall, origin at the bottom, then into UEFN." + _PAID,
       [_n("mesh", "input.mesh", 0, 0, "Model"),
        _n("r", "mesh.remesh", _COL, 0, inputs={"polycount": 8000}, backend="meshy_remesh", topology="triangle"),
        _n("f", "mesh.fit_box", _COL * 2, 0, inputs={"height": 1}),
        _n("o", "mesh.set_origin", _COL * 3, 0, x="center", y="min", z="center"),
        _n("u", "uefn.import", _COL * 4, 0, folder="Ducky/Props"),
        _n("p", "util.preview", _COL * 5, 0, "In UEFN")],
       [_w("mesh", "mesh", "r", "mesh"), _w("r", "mesh", "f", "mesh"), _w("f", "mesh", "o", "mesh"), _w("o", "mesh", "u", "file"), _w("u", "asset", "p", "value")]),
    _t("pipe-restyle", "Restyle a model", "🖌️", "3D",
       "Pick a model and describe a look; it is painted again in that style (Meshy)." + _PAID,
       [_n("mesh", "input.mesh", 0, 0, "Model"), _n("style", "input.text", 0, 160, "Style", value="hand-painted, bright cartoon colors"),
        _n("rt", "mesh.retexture", _COL, 60, backend="meshy_retexture"), _n("p", "util.preview", _COL * 2, 60, "Restyled")],
       [_w("mesh", "mesh", "rt", "mesh"), _w("style", "text", "rt", "prompt"), _w("rt", "mesh", "p", "value")]),
    _t("pipe-extract-textures", "Pull the textures out of a model", "🗂️", "3D",
       "Pick a GLB; its base color, roughness, metallic and normal maps come out as pictures. Free.",
       [_n("mesh", "input.mesh", 0, 0, "Model"), _n("x", "mesh.textures_extract", _COL, 0),
        _n("p1", "util.preview", _COL * 2, -80, "Base color"), _n("p2", "util.preview", _COL * 2, 120, "Normal")],
       [_w("mesh", "mesh", "x", "mesh"), _w("x", "base_color", "p1", "value"), _w("x", "normal", "p2", "value")]),
    _t("pipe-model-check", "Check a model's size", "📏", "3D",
       "Width, height, depth, triangles and whether it's rigged, before you import it. Free.",
       [_n("mesh", "input.mesh", 0, 0, "Model"), _n("i", "mesh.info", _COL, 0), _n("p", "util.preview", _COL * 2, 0, "Info")],
       [_w("mesh", "mesh", "i", "mesh"), _w("i", "info", "p", "value")]),
    _t("pipe-blender-render", "Render a model in Blender", "🎬", "3D",
       "A picture of the model from Blender (auto camera and light). Needs Blender open with its MCP add-on.",
       [_n("mesh", "input.mesh", 0, 0, "Model"), _n("r", "blender.render", _COL, 0, inputs={"size": 1024}, transparent=True),
        _n("p", "util.preview", _COL * 2, 0, "Render")],
       [_w("mesh", "mesh", "r", "mesh"), _w("r", "image", "p", "value")]),
    # ------------------------------------------------------------------ Characters
    _t("pipe-character-prompt", "Prompt → character → rig → animations → UEFN", "🕺", "Characters",
       "A character from your prompt (Meshy), rigged (walk and run included), three animations (Idle, Wave, Victory), all imported into UEFN." + _PAID,
       [_n("q", "input.text", 0, 0, "Character", value="A cartoon duck adventurer, full body, T-pose, game character"),
        _n("m", "mesh.generate", _COL, 0, backend="meshy_text_to_3d"),
        _n("r", "mesh.rig", _COL * 2, 0, inputs={"height": 1.7}),
        _n("a", "mesh.animate", _COL * 3, 0, actions="11, 28, 59"),
        _n("u", "uefn.import", _COL * 4, 0, folder="Ducky/Characters"),
        _n("p", "util.preview", _COL * 5, 0, "In UEFN")],
       [_w("q", "text", "m", "prompt"), _w("m", "mesh", "r", "mesh"), _w("r", "mesh", "a", "mesh"),
        _w("a", "meshes", "u", "file"), _w("u", "assets", "p", "value")]),
    _t("pipe-character-full", "Prompt → picture → character → rig → animations → UEFN", "🦆", "Characters",
       "The whole character pipeline: a concept picture from your prompt, background removed, made 3D, rigged, animated and imported into UEFN." + _PAID,
       [_n("q", "input.text", 0, 0, "Character", value="A cartoon duck knight, full body, front view, T-pose, plain background"),
        _n("gen", "image.generate", _COL, 0, backend="gemini25flash"),
        _n("cut", "image.remove_bg", _COL * 2, 0),
        _n("m", "mesh.from_image", _COL * 3, 0, backend="meshy_image_to_3d"),
        _n("r", "mesh.rig", _COL * 4, 0, inputs={"height": 1.7}),
        _n("a", "mesh.animate", _COL * 5, 0, actions="11, 28, 59"),
        _n("u", "uefn.import", _COL * 6, 0, folder="Ducky/Characters"),
        _n("p", "util.preview", _COL * 7, 0, "In UEFN")],
       [_w("q", "text", "gen", "prompt"), _w("gen", "image", "cut", "image"), _w("cut", "image", "m", "image"),
        _w("m", "mesh", "r", "mesh"), _w("r", "mesh", "a", "mesh"), _w("a", "meshes", "u", "file"), _w("u", "assets", "p", "value")]),
    _t("pipe-character-picture", "Picture → character → rig → animations → UEFN", "🧍", "Characters",
       "Your character art (full body, T-pose works best) made 3D, rigged, animated and imported into UEFN." + _PAID,
       [_n("img", "input.image", 0, 0, "Character art"),
        _n("m", "mesh.from_image", _COL, 0, backend="meshy_image_to_3d"),
        _n("r", "mesh.rig", _COL * 2, 0, inputs={"height": 1.7}),
        _n("a", "mesh.animate", _COL * 3, 0, actions="11, 28, 59"),
        _n("u", "uefn.import", _COL * 4, 0, folder="Ducky/Characters"),
        _n("p", "util.preview", _COL * 5, 0, "In UEFN")],
       [_w("img", "image", "m", "image"), _w("m", "mesh", "r", "mesh"), _w("r", "mesh", "a", "mesh"),
        _w("a", "meshes", "u", "file"), _w("u", "assets", "p", "value")]),
    # ------------------------------------------------------------------ Text & AI
    _t("pipe-describe-picture", "Describe a picture", "👁️", "Text & AI",
       "A model that can see describes the picture for a game artist (pick the model in its details).",
       [_n("img", "input.image", 0, 0, "Picture"),
        _n("v", "llm.vision", _COL, 0, inputs={"prompt": "Describe this for a game artist: subject, style, colors and materials."}),
        _n("p", "util.preview", _COL * 2, 0, "Description")],
       [_w("img", "image", "v", "image"), _w("v", "text", "p", "value")]),
    _t("pipe-translate", "Translate text", "🌍", "Text & AI",
       "Text into another language (set it in the Translate node).",
       [_n("q", "input.text", 0, 0, "Text", value="Collect 10 golden eggs to open the gate!"),
        _n("t", "llm.translate", _COL, 0, language="Spanish"), _n("p", "util.preview", _COL * 2, 0, "Translation")],
       [_w("q", "text", "t", "text"), _w("t", "text", "p", "value")]),
    _t("pipe-extract-data", "Pull data out of text", "🧾", "Text & AI",
       "A model reads the text and fills the fields you name; each field is its own output.",
       [_n("q", "input.text", 0, 0, "Text", value="Duck Knight is level 12 with 340 HP, carries a sword and shield and is rare."),
        _n("x", "llm.extract", _COL, 0, names=["name", "level", "health", "items", "rarity"]),
        _n("p", "util.preview", _COL * 2, 0, "Data")],
       [_w("q", "text", "x", "text"), _w("x", "data", "p", "value")]),
    _t("pipe-find-pictures", "Find matching pictures", "🔎", "Text & AI",
       "Pick a pile of pictures; a model keeps the ones that match what you ask (by their names).",
       [_n("imgs", "input.images", 0, 0, "Pictures"),
        _n("f", "llm.pick", _COL, 0, inputs={"prompt": "pictures of ducks"}),
        _n("p", "util.preview", _COL * 2, 0, "Matches")],
       [_w("imgs", "images", "f", "list"), _w("f", "list", "p", "value")]),
    # ------------------------------------------------------------------ Documents
    _t("pipe-pdf-summary", "Summarize a PDF", "📄", "Documents",
       "The text of a PDF, summed up by the model you pick.",
       [_n("pdf", "input.pdf", 0, 0, "PDF"), _n("t", "pdf.text", _COL, 0),
        _n("a", "llm.ask", _COL * 2, 0, inputs={"prompt": "Summarize this document in five short bullet points."}),
        _n("p", "util.preview", _COL * 3, 0, "Summary")],
       [_w("pdf", "pdf", "t", "pdf"), _w("t", "text", "a", "context"), _w("a", "text", "p", "value")]),
    _t("pipe-pdf-sheet", "PDF pictures to one sheet", "📑", "Documents",
       "Every picture inside a PDF, laid out on one sheet. Free.",
       [_n("pdf", "input.pdf", 0, 0, "PDF"), _n("x", "pdf.images", _COL, 0), _n("sheet", "image.concat", _COL * 2, 0, direction="grid", gap=8),
        _n("p", "util.preview", _COL * 3, 0, "Sheet")],
       [_w("pdf", "pdf", "x", "pdf"), _w("x", "images", "sheet", "images"), _w("sheet", "image", "p", "value")]),
]

# Older builtins: which shelf they sit on.
BUILTIN_CATEGORIES = {
    "builtin:playtest-start": "Play tests",
    "builtin:stop-game": "Play tests",
    "builtin:tycoon-first-purchase": "Play tests",
    "builtin:tycoon-income-loop": "Play tests",
    "builtin:tycoon-ducky-playtest": "Play tests",
}
