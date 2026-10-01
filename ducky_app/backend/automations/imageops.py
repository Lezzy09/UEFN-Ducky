"""Free image tools that run on this PC with Pillow (plan §6, Images [P2, local]):
resize, crop, convert, split / combine alpha and channels, put images together, and
render text to an image. Each writes its result into the run's folder for the node."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.automations.files import file_ref, with_url
from backend.automations.media import path_of

_FORMATS = {"png": ("PNG", ".png"), "jpg": ("JPEG", ".jpg"), "webp": ("WEBP", ".webp")}
_MAX_SIDE = 16384


def _open(inputs: dict[str, Any], pin: str, what: str = "Image"):
    from PIL import Image, ImageOps

    path = path_of(inputs.get(pin))
    if not path:
        raise ValueError(f"Nothing in {what}: wire an image in or pick one in the details.")
    if not Path(path).is_file():
        raise ValueError(f"{what} {Path(path).name} isn't on this PC any more.")
    with Image.open(path) as img:
        img.load()
        return ImageOps.exif_transpose(img) or img


def _size(inputs: dict[str, Any], cfg: dict[str, Any], key: str) -> int:
    for raw in (inputs.get(key), cfg.get(key)):
        try:
            if raw not in (None, ""):
                value = int(float(raw))
                if value < 0 or value > _MAX_SIDE:
                    raise ValueError(f"{key.title()} must be between 0 and {_MAX_SIDE}.")
                return value
        except (TypeError, ValueError) as exc:
            if "must be" in str(exc):
                raise
    return 0


def _save(img, folder: Path, name: str, fmt: str = "png", quality: int = 90) -> dict[str, Any]:
    kind, ext = _FORMATS.get(fmt, _FORMATS["png"])
    if kind == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}{ext}"
    img.save(target, kind, **({"quality": max(1, min(100, int(quality)))} if kind in ("JPEG", "WEBP") else {}))
    return with_url(file_ref(target, "image"))


def resize(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image, ImageOps

    img = _open(inputs, "image")
    width, height = _size(inputs, cfg, "width"), _size(inputs, cfg, "height")
    if not width and not height:
        raise ValueError("Set a width, a height or both.")
    if not width:
        width = max(1, round(img.width * height / img.height))
    if not height:
        height = max(1, round(img.height * width / img.width))
    mode = str(cfg.get("mode") or "fit")
    if mode == "stretch":
        out = img.resize((width, height), Image.Resampling.LANCZOS)
    elif mode == "fill":
        out = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)
    else:
        out = img.copy()
        out.thumbnail((width, height), Image.Resampling.LANCZOS)
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}, "result": {"width": out.width, "height": out.height}}


def crop(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    img = _open(inputs, "image")
    x, y = _size(inputs, cfg, "x"), _size(inputs, cfg, "y")
    width = _size(inputs, cfg, "width") or img.width - x
    height = _size(inputs, cfg, "height") or img.height - y
    if x >= img.width or y >= img.height or width <= 0 or height <= 0:
        raise ValueError(f"That crop is outside the {img.width}×{img.height} image.")
    out = img.crop((x, y, min(img.width, x + width), min(img.height, y + height)))
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}, "result": {"width": out.width, "height": out.height}}


def convert(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    img = _open(inputs, "image")
    fmt = str(cfg.get("format") or "png")
    quality = _size(inputs, cfg, "quality") or 90
    return {"ok": True, "outputs": {"image": _save(img, folder, "image", fmt, quality)}}


def split_alpha(_cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    img = _open(inputs, "image").convert("RGBA")
    return {"ok": True, "outputs": {
        "color": _save(img.convert("RGB"), folder, "color"),
        "alpha": _save(img.getchannel("A"), folder, "alpha"),
    }}


def combine_alpha(_cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image

    color = _open(inputs, "color", "Color").convert("RGB")
    alpha = _open(inputs, "alpha", "Alpha").convert("L")
    if alpha.size != color.size:
        alpha = alpha.resize(color.size, Image.Resampling.LANCZOS)
    out = color.copy()
    out.putalpha(alpha)
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}}


def split_channels(_cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    img = _open(inputs, "image").convert("RGBA")
    names = ("red", "green", "blue", "alpha")
    return {"ok": True, "outputs": {name: _save(channel, folder, name) for name, channel in zip(names, img.split())}}


def combine_channels(_cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image

    channels = {}
    for name in ("red", "green", "blue", "alpha"):
        if path_of(inputs.get(name)):
            channels[name] = _open(inputs, name, name.title()).convert("L")
    if not channels:
        raise ValueError("Wire at least one channel in.")
    size = next(iter(channels.values())).size
    blank, full = Image.new("L", size, 0), Image.new("L", size, 255)
    bands = [channels.get(name, blank if name != "alpha" else full) for name in ("red", "green", "blue", "alpha")]
    bands = [band if band.size == size else band.resize(size, Image.Resampling.LANCZOS) for band in bands]
    out = Image.merge("RGBA", bands)
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}}


def concat(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image

    raw = inputs.get("images")
    items = raw if isinstance(raw, list) else [raw] if raw else []
    images = [_open({"image": item}, "image") for item in items if path_of(item)]
    if not images:
        raise ValueError("Nothing in Images: wire several images in.")
    gap = _size(inputs, cfg, "gap")
    direction = str(cfg.get("direction") or "row")
    columns = len(images) if direction == "row" else 1 if direction == "column" else max(1, _size(inputs, cfg, "columns") or round(len(images) ** 0.5 + 0.49))
    rows = [images[i:i + columns] for i in range(0, len(images), columns)]
    cell_w = [max(row[c].width for row in rows if c < len(row)) for c in range(columns)]
    row_h = [max(img.height for img in row) for row in rows]
    width = sum(cell_w) + gap * (columns - 1)
    height = sum(row_h) + gap * (len(rows) - 1)
    if width > _MAX_SIDE or height > _MAX_SIDE:
        raise ValueError(f"That would be {width}×{height}; keep it under {_MAX_SIDE} on each side.")
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    y = 0
    for r, row in enumerate(rows):
        x = 0
        for c, img in enumerate(row):
            out.paste(img.convert("RGBA"), (x, y))
            x += cell_w[c] + gap
        y += row_h[r] + gap
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}, "result": {"width": width, "height": height}}


def _font(size: int):
    from PIL import ImageFont

    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _color(raw: Any, fallback: str) -> str:
    from PIL import ImageColor

    text = str(raw or "").strip() or fallback
    try:
        ImageColor.getrgb(text)
    except ValueError as exc:
        raise ValueError(f"{text} isn't a color (try #ffcc00 or white).") from exc
    return text


def render_text(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    raw = inputs.get("text")
    text = raw if isinstance(raw, str) else "" if raw is None else str(raw)
    if not text.strip():
        raise ValueError("Nothing in Text: wire text in or type it in the details.")
    size = _size(inputs, cfg, "size") or 64
    width, height = _size(inputs, cfg, "width") or 1024, _size(inputs, cfg, "height") or 512
    background = str(cfg.get("background") or "").strip()
    out = Image.new("RGBA", (width, height), _color(background, "#00000000") if background else (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    font = _font(size)
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    x = (width - (box[2] - box[0])) / 2 - box[0]
    y = (height - (box[3] - box[1])) / 2 - box[1]
    draw.multiline_text((x, y), text, font=font, fill=_color(cfg.get("color"), "white"), align="center")
    return {"ok": True, "outputs": {"image": _save(out, folder, "image")}}


OPS = {
    "image.resize": resize,
    "image.crop": crop,
    "image.convert": convert,
    "image.split_alpha": split_alpha,
    "image.combine_alpha": combine_alpha,
    "image.split_channels": split_channels,
    "image.combine_channels": combine_channels,
    "image.concat": concat,
    "image.text": render_text,
}
