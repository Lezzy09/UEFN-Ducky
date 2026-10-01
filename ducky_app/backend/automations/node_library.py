"""Image, 3D, Blender, UEFN, list, document and model nodes for the workflow palette
(plan §6, P2). Every one is a value node (no white pins): it runs when something
needs what it makes, or on its own as the end of a pipeline."""

from __future__ import annotations

from typing import Any


def _pin(pid: str, label: str, ptype: str, *, required: bool = False) -> dict[str, Any]:
    return {"id": pid, "label": label, "type": ptype, **({"required": True} if required else {})}


def _select(fid: str, label: str, options: list[tuple[str, str]]) -> dict[str, Any]:
    return {"id": fid, "label": label, "type": "select", "options": [{"id": oid, "label": text} for oid, text in options]}


_BACKEND = {"id": "backend", "label": "Backend", "type": "backend"}
_SPEND = {"id": "spend", "label": "Spend credits", "type": "boolean"}
_MODEL = {"id": "model", "label": "Model", "type": "model"}
_MESH_IN = _pin("mesh", "3D model", "mesh", required=True)
_MESH_OUT = _pin("mesh", "3D model", "mesh")
_IMAGE_IN = _pin("image", "Image", "image", required=True)
_IMAGE_OUT = _pin("image", "Image", "image")
_FILES_OUT = _pin("files", "All files", "json")


def _node(ntype: str, label: str, group: str, role: str, description: str, *, inputs=(), outputs=(), fields=(), paid: bool = False) -> dict[str, Any]:
    return {
        "type": ntype, "label": label, "group": group, "role": role, "exec": False, "description": description,
        "inputs": list(inputs), "outputs": list(outputs),
        "config_fields": ([_BACKEND, _SPEND] if paid else []) + list(fields),
        **({"paid": True} if paid else {}),
    }


_ORIGIN = [("min", "Min side"), ("center", "Center"), ("max", "Max side"), ("mass", "Center of mass"), ("keep", "Leave as is")]

LIBRARY: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ Text & AI
    _node("llm.vision", "Ask about an image", "Text & AI", "agent",
          "Shows the picture(s) to a model that can see and passes its answer on: describe it, read text off it, check it.",
          inputs=[_pin("image", "Image", "images", required=True), _pin("prompt", "Question", "text")],
          outputs=[_pin("text", "Answer", "text")],
          fields=[_MODEL, {"id": "system", "label": "Instructions", "type": "textarea"}]),
    _node("llm.extract", "Extract data", "Text & AI", "agent",
          "A model reads the text and fills the fields you name; each field becomes its own output.",
          inputs=[_pin("text", "Text", "text", required=True)],
          outputs=[_pin("data", "Data", "json")],
          fields=[{"id": "names", "label": "Fields", "type": "names"}, _MODEL, {"id": "system", "label": "Hints", "type": "textarea"}]),
    _node("llm.translate", "Translate", "Text & AI", "agent",
          "Translates text into the language you set, keeping its formatting.",
          inputs=[_pin("text", "Text", "text", required=True), _pin("language", "Language", "text")],
          outputs=[_pin("text", "Translation", "text")],
          fields=[{"id": "language", "label": "Language", "type": "string"}, _MODEL]),
    _node("llm.pick", "Find by description", "Text & AI", "agent",
          "A model picks the items of a list (files, meshes, text) that match what you ask, best first.",
          inputs=[_pin("list", "List", "json", required=True), _pin("prompt", "Looking for", "text", required=True)],
          outputs=[_pin("list", "Matches", "json"), _pin("item", "Best match", "any"), _pin("count", "Count", "number")],
          fields=[_MODEL]),
    # ------------------------------------------------------------------ Images (generators)
    _node("image.generate", "Text to Image", "Images", "action",
          "Makes a picture from your prompt on the backend you pick (Gemini, SeeDream, Meshy).",
          inputs=[_pin("prompt", "Prompt", "text", required=True)], outputs=[_IMAGE_OUT, _FILES_OUT], paid=True),
    _node("image.edit", "Edit Image", "Images", "action",
          "Changes a picture the way your prompt says (new background, style, add or remove things).",
          inputs=[_IMAGE_IN, _pin("prompt", "Prompt", "text", required=True)], outputs=[_IMAGE_OUT, _FILES_OUT], paid=True),
    _node("image.remove_bg", "Remove Background", "Images", "action",
          "Cuts the subject out onto a see-through background.",
          inputs=[_IMAGE_IN], outputs=[_IMAGE_OUT, _FILES_OUT], paid=True),
    _node("image.upscale", "Upscale Image", "Images", "action",
          "Makes a picture bigger and sharper.",
          inputs=[_IMAGE_IN], outputs=[_IMAGE_OUT, _FILES_OUT], paid=True),
    # ------------------------------------------------------------------ Image tools (free, on this PC)
    _node("image.resize", "Resize Image", "Image tools", "function",
          "Resizes to a width and/or height: fit inside, fill and crop, or stretch.",
          inputs=[_IMAGE_IN, _pin("width", "Width", "number"), _pin("height", "Height", "number")], outputs=[_IMAGE_OUT],
          fields=[_select("mode", "How", [("fit", "Fit inside"), ("fill", "Fill and crop"), ("stretch", "Stretch")])]),
    _node("image.crop", "Crop Image", "Image tools", "function",
          "Keeps the rectangle you set (pixels from the top left).",
          inputs=[_IMAGE_IN, _pin("x", "X", "number"), _pin("y", "Y", "number"), _pin("width", "Width", "number"), _pin("height", "Height", "number")],
          outputs=[_IMAGE_OUT]),
    _node("image.convert", "Convert Image", "Image tools", "function",
          "Saves the picture as PNG, JPG or WebP.",
          inputs=[_IMAGE_IN], outputs=[_IMAGE_OUT],
          fields=[_select("format", "Format", [("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")]), {"id": "quality", "label": "Quality (1-100)", "type": "number"}]),
    _node("image.split_alpha", "Split Alpha", "Image tools", "function",
          "Splits a picture into its colors and its see-through mask.",
          inputs=[_IMAGE_IN], outputs=[_pin("color", "Color", "image"), _pin("alpha", "Alpha", "image")]),
    _node("image.combine_alpha", "Combine Alpha", "Image tools", "function",
          "Uses a black-and-white picture as the see-through mask of another.",
          inputs=[_pin("color", "Color", "image", required=True), _pin("alpha", "Alpha", "image", required=True)], outputs=[_IMAGE_OUT]),
    _node("image.split_channels", "Split Channels", "Image tools", "function",
          "Splits a picture into red, green, blue and alpha pictures (packed texture maps).",
          inputs=[_IMAGE_IN],
          outputs=[_pin("red", "Red", "image"), _pin("green", "Green", "image"), _pin("blue", "Blue", "image"), _pin("alpha", "Alpha", "image")]),
    _node("image.combine_channels", "Combine Channels", "Image tools", "function",
          "Packs up to four black-and-white pictures into one (red, green, blue, alpha).",
          inputs=[_pin("red", "Red", "image"), _pin("green", "Green", "image"), _pin("blue", "Blue", "image"), _pin("alpha", "Alpha", "image")],
          outputs=[_IMAGE_OUT]),
    _node("image.concat", "Combine Images", "Image tools", "function",
          "Puts pictures side by side, stacked, or in a grid (sprite sheets, contact sheets).",
          inputs=[_pin("images", "Images", "images", required=True)], outputs=[_IMAGE_OUT],
          fields=[_select("direction", "Layout", [("row", "Side by side"), ("column", "Stacked"), ("grid", "Grid")]),
                  {"id": "columns", "label": "Columns (grid)", "type": "number"}, {"id": "gap", "label": "Gap (px)", "type": "number"}]),
    _node("image.text", "Text to Picture", "Image tools", "function",
          "Draws text onto a picture: titles, labels, signs.",
          inputs=[_pin("text", "Text", "text", required=True)], outputs=[_IMAGE_OUT],
          fields=[{"id": "size", "label": "Text size (px)", "type": "number"}, {"id": "width", "label": "Width (px)", "type": "number"},
                  {"id": "height", "label": "Height (px)", "type": "number"}, {"id": "color", "label": "Text color", "type": "string"},
                  {"id": "background", "label": "Background (blank = see-through)", "type": "string"}]),
    # ------------------------------------------------------------------ 3D (generators and cloud tools)
    _node("mesh.generate", "Text to 3D", "3D", "action",
          "Makes a textured 3D model from your prompt (Meshy, Tripo, Hunyuan).",
          inputs=[_pin("prompt", "Prompt", "text", required=True)], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.from_image", "Image to 3D", "3D", "action",
          "Makes a 3D model from one picture (Meshy, TRELLIS, Tripo, Hunyuan). Can try the next backend when one fails.",
          inputs=[_IMAGE_IN, _pin("prompt", "Texture hint", "text")], outputs=[_MESH_OUT, _FILES_OUT],
          fields=[{"id": "fallback", "label": "Try the next backend if it fails", "type": "boolean"}], paid=True),
    _node("mesh.multi_view", "Multi-view to 3D", "3D", "action",
          "Makes a 3D model from 2–4 pictures of the same thing from different sides.",
          inputs=[_pin("images", "Views", "images", required=True)], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.retexture", "(Re)Texture Mesh", "3D", "action",
          "Paints a model again from a style prompt or a style picture.",
          inputs=[_MESH_IN, _pin("prompt", "Style", "text"), _pin("style_image", "Style image", "image")], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.remesh", "Optimize Mesh", "3D", "action",
          "Rebuilds the model with fewer (or more) polygons, triangles or quads.",
          inputs=[_MESH_IN, _pin("polycount", "Target polygons", "number")], outputs=[_MESH_OUT, _FILES_OUT],
          fields=[_select("topology", "Topology", [("triangle", "Triangles"), ("quad", "Quads")])], paid=True),
    _node("mesh.uv_unwrap", "UV Unfold", "3D", "action",
          "Makes new UV coordinates so textures map cleanly.",
          inputs=[_MESH_IN], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.convert", "Convert 3D Model", "3D", "action",
          "Turns a model into FBX, GLB, OBJ, USDZ, STL or PLY.",
          inputs=[_MESH_IN], outputs=[_MESH_OUT, _FILES_OUT],
          fields=[_select("format", "Format", [("fbx", "FBX"), ("glb", "GLB"), ("obj", "OBJ"), ("usdz", "USDZ"), ("stl", "STL"), ("ply", "PLY")])], paid=True),
    _node("mesh.repair", "Repair Mesh", "3D", "action",
          "Fixes holes and broken geometry in a generated model.",
          inputs=[_MESH_IN], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.bake", "Bake High Poly to Low Poly", "3D", "action",
          "Bakes the detail and materials of a high-poly model onto a low-poly one.",
          inputs=[_pin("high", "High poly", "mesh", required=True), _pin("low", "Low poly", "mesh", required=True)], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.render", "Render Mesh", "3D", "action",
          "A picture of a generated model, rendered in the cloud.",
          inputs=[_MESH_IN], outputs=[_IMAGE_OUT, _FILES_OUT], paid=True),
    # ------------------------------------------------------------------ Characters
    _node("mesh.rig", "Rig Humanoid Mesh", "Characters", "action",
          "Adds a skeleton to a textured humanoid model so it can be animated (walk and run included).",
          inputs=[_MESH_IN, _pin("height", "Height (m)", "number")], outputs=[_MESH_OUT, _FILES_OUT], paid=True),
    _node("mesh.animate", "Animate Rigged Mesh", "Characters", "action",
          "Applies up to ten animations from the Meshy library to a rigged character (one model per animation).",
          inputs=[_MESH_IN, _pin("actions", "Animations", "text")],
          outputs=[_MESH_OUT, _pin("meshes", "All animations", "json"), _FILES_OUT],
          fields=[{"id": "actions", "label": "Animation numbers (Idle 1 = 11, Big Wave = 28, Victory Cheer = 59, Attack = 4)", "type": "string"}], paid=True),
    # ------------------------------------------------------------------ 3D tools (free, on this PC, GLB)
    _node("mesh.info", "Mesh Info", "3D tools", "function",
          "The model's size, triangle count, materials, and whether it is rigged or animated.",
          inputs=[_MESH_IN],
          outputs=[_pin("width", "Width", "number"), _pin("height", "Height", "number"), _pin("depth", "Depth", "number"),
                   _pin("triangles", "Triangles", "number"), _pin("info", "Info", "json")]),
    _node("mesh.fit_box", "Mesh BBox Fit", "3D tools", "function",
          "Scales the model to a width (X), height (Y) and depth (Z); keeps proportions unless Stretch is on.",
          inputs=[_MESH_IN, _pin("width", "Width", "number"), _pin("height", "Height", "number"), _pin("depth", "Depth", "number")],
          outputs=[_MESH_OUT], fields=[{"id": "stretch", "label": "Stretch to every size", "type": "boolean"}]),
    _node("mesh.set_origin", "Set Mesh Origin", "3D tools", "function",
          "Moves the model so its pivot sits at the side, center or center of mass you pick on each axis.",
          inputs=[_MESH_IN], outputs=[_MESH_OUT],
          fields=[_select("x", "X (left/right)", _ORIGIN), _select("y", "Y (bottom/top)", _ORIGIN), _select("z", "Z (back/front)", _ORIGIN)]),
    _node("mesh.origin_text", "Text to Origin", "3D tools", "agent",
          "Say where the pivot goes (\"bottom centre\", \"back left corner\") and a model sets it.",
          inputs=[_MESH_IN, _pin("instruction", "Where", "text", required=True)], outputs=[_MESH_OUT], fields=[_MODEL]),
    _node("mesh.rotate", "Rotate Mesh", "3D tools", "function",
          "Turns the model around X, then Y, then Z (degrees) about the origin.",
          inputs=[_MESH_IN, _pin("x", "X°", "number"), _pin("y", "Y°", "number"), _pin("z", "Z°", "number")], outputs=[_MESH_OUT]),
    _node("mesh.textures_extract", "Extract Texture Maps", "3D tools", "function",
          "Takes the base color, roughness, metallic, normal, occlusion and emissive maps out of a model.",
          inputs=[_MESH_IN, _pin("material", "Material #", "number")],
          outputs=[_pin("base_color", "Base color", "image"), _pin("roughness", "Roughness", "image"), _pin("metallic", "Metallic", "image"),
                   _pin("normal", "Normal", "image"), _pin("occlusion", "Occlusion", "image"), _pin("emissive", "Emissive", "image")]),
    _node("mesh.textures_apply", "Apply Textures to Mesh", "3D tools", "function",
          "Puts texture maps on a model (every material): base color, roughness, metallic, normal, occlusion.",
          inputs=[_MESH_IN, _pin("base_color", "Base color", "image"), _pin("roughness", "Roughness", "image"), _pin("metallic", "Metallic", "image"),
                  _pin("normal", "Normal", "image"), _pin("occlusion", "Occlusion", "image")],
          outputs=[_MESH_OUT]),
    # ------------------------------------------------------------------ Blender
    _node("blender.open", "Open in Blender", "Blender", "action",
          "Imports the model into the Blender that is open (needs Blender with its MCP add-on).",
          inputs=[_MESH_IN], outputs=[_MESH_OUT]),
    _node("blender.render", "Render in Blender", "Blender", "action",
          "Renders the model in Blender (a temporary scene, auto camera and light) to a picture.",
          inputs=[_MESH_IN, _pin("size", "Size (px)", "number")], outputs=[_IMAGE_OUT],
          fields=[{"id": "transparent", "label": "See-through background", "type": "boolean"}]),
    _node("blender.export", "Blender Scene to GLB", "Blender", "action",
          "Saves what is open in Blender (or only the selection) as a GLB for other 3D nodes.",
          outputs=[_MESH_OUT], fields=[{"id": "selected", "label": "Only what is selected", "type": "boolean"}]),
    # ------------------------------------------------------------------ UEFN
    _node("uefn.import", "Send to UEFN", "UEFN", "end",
          "Imports models, pictures or sounds (one, or a whole list) into the open project's Content Browser (UEFN must be running).",
          inputs=[_pin("file", "Files", "any", required=True), _pin("folder", "Content folder", "text")],
          outputs=[_pin("asset", "Asset path", "text"), _pin("assets", "Every asset", "json")],
          fields=[{"id": "folder", "label": "Content folder", "type": "string"}, {"id": "replace", "label": "Replace if it exists", "type": "boolean"}]),
    # ------------------------------------------------------------------ Lists
    _node("list.make", "Make List", "Lists", "logic",
          "Puts the values wired in into one list.",
          outputs=[_pin("list", "List", "json")], fields=[{"id": "names", "label": "Inputs", "type": "names"}]),
    _node("list.get", "Get Item", "Lists", "logic",
          "One item of a list by its place: 0 is the first, -1 the last.",
          inputs=[_pin("list", "List", "json", required=True), _pin("index", "Index", "number")], outputs=[_pin("item", "Item", "any")]),
    _node("list.count", "Count", "Lists", "logic",
          "How many items a list has (or letters in a text).",
          inputs=[_pin("list", "List", "json", required=True)], outputs=[_pin("count", "Count", "number")]),
    _node("list.join", "Join List", "Lists", "logic",
          "Joins a list into one text with a separator (\\n for new lines).",
          inputs=[_pin("list", "List", "json", required=True), _pin("separator", "Separator", "text")], outputs=[_pin("text", "Text", "text")]),
    _node("list.filter", "Filter List", "Lists", "logic",
          "Keeps the items your expression says yes to: item is each value, index its place (item.name.endsWith(\".png\")).",
          inputs=[_pin("list", "List", "json", required=True)], outputs=[_pin("list", "Kept", "json"), _pin("count", "Count", "number")],
          fields=[{"id": "expression", "label": "Keep when", "type": "expression"}]),
    _node("list.map", "Transform Each", "Lists", "logic",
          "Turns every item into something else with an expression (item * 2, item.name).",
          inputs=[_pin("list", "List", "json", required=True)], outputs=[_pin("list", "List", "json")],
          fields=[{"id": "expression", "label": "Each becomes", "type": "expression"}]),
    # ------------------------------------------------------------------ Documents
    _node("pdf.text", "Extract Text from Document", "Documents", "action",
          "The text of a PDF (all pages, or the ones you list like 1-3, 5).",
          inputs=[_pin("pdf", "PDF", "pdf", required=True), _pin("pages", "Pages", "text")],
          outputs=[_pin("text", "Text", "text"), _pin("page_texts", "Each page", "json")]),
    _node("pdf.images", "Extract Images from Document", "Documents", "action",
          "Every picture inside a PDF.",
          inputs=[_pin("pdf", "PDF", "pdf", required=True), _pin("pages", "Pages", "text")],
          outputs=[_pin("images", "Images", "images"), _pin("count", "Count", "number")]),
    # ------------------------------------------------------------------ Utility
    _node("util.save_file", "Save File", "Utility", "end",
          "Copies what is wired in into a folder you pick (keeps both if a file has the same name).",
          inputs=[_pin("file", "File", "any", required=True), _pin("folder", "Folder", "text")],
          outputs=[_pin("file", "Saved file", "any"), _pin("path", "Path", "text")],
          fields=[{"id": "folder", "label": "Folder", "type": "folder"}, {"id": "name", "label": "File name (blank = keep)", "type": "string"},
                  {"id": "overwrite", "label": "Overwrite a file with the same name", "type": "boolean"}]),
]
