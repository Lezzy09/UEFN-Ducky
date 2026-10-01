"""Document nodes (plan §6, Documents): the text of a PDF, and the pictures inside it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.automations.files import file_ref, with_url
from backend.automations.media import path_of

_MAX_PAGES = 2000
_MAX_IMAGES = 200


def _reader(inputs: dict[str, Any]):
    from pypdf import PdfReader

    path = path_of(inputs.get("pdf"))
    if not path:
        raise ValueError("Nothing in PDF: wire a PDF in or pick one in the details.")
    if not Path(path).is_file():
        raise ValueError(f"PDF {Path(path).name} isn't on this PC any more.")
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError(f"{Path(path).name} is password protected.") from exc
    return reader, Path(path)


def _pages(raw: Any, count: int) -> list[int]:
    """'1-3, 5' → [0, 1, 2, 4]; blank = every page."""
    text = str(raw or "").strip()
    if not text:
        return list(range(min(count, _MAX_PAGES)))
    out: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                first, last = int(a or 1), int(b or count)
            else:
                first = last = int(part)
        except ValueError as exc:
            raise ValueError(f"Pages should look like 1-3, 5 (not {text}).") from exc
        for page in range(max(1, first), min(count, last) + 1):
            if page - 1 not in out:
                out.append(page - 1)
    if not out:
        raise ValueError(f"None of those pages exist; it has {count}.")
    return out[:_MAX_PAGES]


def text(cfg: dict[str, Any], inputs: dict[str, Any], _folder: Path) -> dict[str, Any]:
    reader, source = _reader(inputs)
    pages = _pages(inputs.get("pages") or cfg.get("pages"), len(reader.pages))
    parts = [(reader.pages[i].extract_text() or "").strip() for i in pages]
    joined = "\n\n".join(part for part in parts if part)
    return {"ok": True, "outputs": {"text": joined, "page_texts": parts}, "result": {"file": source.name, "pages": len(pages), "characters": len(joined)}}


def images(cfg: dict[str, Any], inputs: dict[str, Any], folder: Path) -> dict[str, Any]:
    reader, source = _reader(inputs)
    pages = _pages(inputs.get("pages") or cfg.get("pages"), len(reader.pages))
    folder.mkdir(parents=True, exist_ok=True)
    found: list[dict[str, Any]] = []
    for page_index in pages:
        for n, image in enumerate(reader.pages[page_index].images):
            if len(found) >= _MAX_IMAGES:
                break
            name = Path(image.name or f"image{n}").stem
            try:
                img = image.image
            except Exception:
                img = None
            if img is not None:
                target = folder / f"page{page_index + 1}-{n + 1}-{name}.png"
                img.save(target, "PNG")
            else:
                target = folder / f"page{page_index + 1}-{n + 1}-{Path(image.name or 'image.bin').name}"
                target.write_bytes(image.data)
            found.append(with_url(file_ref(target, "image")))
    return {"ok": True, "outputs": {"images": found, "count": len(found)}, "result": {"file": source.name, "images": len(found)}}


OPS = {"pdf.text": text, "pdf.images": images}
