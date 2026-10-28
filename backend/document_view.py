"""Render uploaded documents and locate evidence on their real pages."""

from __future__ import annotations

import os
import io
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata

import pymupdf
from PIL import Image, ImageOps


_conversion_lock = threading.Lock()


class ViewUnavailable(RuntimeError):
    pass


def view_pdf_path(source: str | Path) -> Path:
    path = Path(source)
    if path.suffix.lower() == ".pdf":
        return path
    if path.suffix.lower() != ".docx":
        raise ViewUnavailable("Для этого формата просмотр страниц недоступен")
    rendered = path.with_name(path.name + ".rendered.pdf")
    with _conversion_lock:
        if rendered.exists() and rendered.stat().st_mtime_ns >= path.stat().st_mtime_ns:
            return rendered
        configured = os.getenv("LIBREOFFICE_BIN", "").strip()
        converter = configured if configured and Path(configured).is_file() else shutil.which("soffice") or shutil.which("libreoffice")
        if not converter:
            raise ViewUnavailable("Для просмотра DOCX с оформлением нужен LibreOffice на сервере")
        # The converted PDF and its destination must share a filesystem:
        # /tmp and the persistent Docker documents volume can be different mounts.
        with tempfile.TemporaryDirectory(prefix=".contract-view-", dir=path.parent) as directory:
            profile = Path(directory) / "profile"
            command = [
                converter,
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless", "--convert-to", "pdf:writer_pdf_Export",
                "--outdir", directory, str(path),
            ]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ViewUnavailable("Не удалось подготовить DOCX к просмотру") from exc
            converted = Path(directory) / (path.stem + ".pdf")
            if result.returncode != 0 or not converted.is_file():
                raise ViewUnavailable("Не удалось подготовить DOCX к просмотру")
            os.replace(converted, rendered)
    return rendered


def render_preview(source: str | Path) -> bytes:
    """Render original first-page formatting at card/retina resolution."""
    path = Path(source)
    if path.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
            image.thumbnail((960, 19200))
            output = io.BytesIO()
            image.save(output, format='PNG')
            return output.getvalue()
    with pymupdf.open(view_pdf_path(path)) as pdf:
        if not pdf:
            raise ViewUnavailable('Документ не содержит страниц')
        page = pdf[0]
        scale = min(2.0, 960 / max(page.rect.width, 1))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png')


def render_page(source: str | Path, number: int) -> bytes:
    if Path(source).suffix.lower() in {".png", ".jpg", ".jpeg"}:
        if number != 1:
            raise IndexError("Страница не найдена")
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1400, 1400 * 20))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    with pymupdf.open(view_pdf_path(source)) as pdf:
        if number < 1 or number > len(pdf):
            raise IndexError("Страница не найдена")
        page = pdf[number - 1]
        scale = min(2.0, 1400 / max(page.rect.width, 1))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")


def page_count(source: str | Path) -> int:
    if Path(source).suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return 1
    with pymupdf.open(view_pdf_path(source)) as pdf:
        return len(pdf)


def _search_terms(evidence: str) -> list[str]:
    clean = re.sub(r"\s+", " ", evidence).strip()
    words = clean.split()
    candidates = [clean]
    if len(words) > 12:
        candidates.append(" ".join(words[:12]))
    if len(words) > 5:
        candidates.extend(" ".join(words[index:index + 5]) for index in (0, max(0, len(words) // 2 - 2)))
    return list(dict.fromkeys(term for term in candidates if len(term) >= 4))


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({'«': '"', '»': '"', '“': '"', '”': '"', '–': '-', '—': '-'}))
    for character in ("\xad", "\u2010", "\u2011"):
        value = value.replace(character, "-")
    return " ".join(value.split())


def _matching_rects(parts, evidence: str, *, join_font_runs: bool = False):
    """Map an exact normalized text span back to its original word/block boxes."""
    text = ""
    spans = []
    previous_rectangle = None
    for content, rectangle, line in parts:
        content = _normalize(content)
        separator = ' ' if text else ''
        if join_font_runs and previous_rectangle is not None:
            # LibreOffice may split one word across Cyrillic/Latin font runs.
            # Join touching boxes on the same physical line, preserving real spaces.
            overlap = min(rectangle.y1, previous_rectangle.y1) - max(rectangle.y0, previous_rectangle.y0)
            height = min(rectangle.height, previous_rectangle.height)
            gap = rectangle.x0 - previous_rectangle.x1
            if overlap > height * .5 and -.5 <= gap <= height * .12:
                separator = ''
        text += separator
        start = len(text)
        text += content
        spans.append((start, len(text), rectangle, line))
        previous_rectangle = rectangle
    start = text.find(_normalize(evidence))
    if start < 0:
        return []
    end = start + len(_normalize(evidence))
    lines = {}
    for left, right, rectangle, line in spans:
        if right > start and left < end:
            if line in lines:
                lines[line] |= rectangle
            else:
                lines[line] = pymupdf.Rect(rectangle)
    return list(lines.values())


def _location(number, rectangles, width, height):
    return {"page": number, "rects": [{"x": rect.x0 / width, "y": rect.y0 / height,
            "width": rect.width / width, "height": rect.height / height} for rect in rectangles[:12]]}


def locate_evidence(source: str | Path, evidence: str, preferred_page: int | None = None, *, document_ir: dict | None = None) -> dict | None:
    if not evidence or not evidence.strip():
        return None
    image = Path(source).suffix.lower() in {".png", ".jpg", ".jpeg"}
    if not image:
        with pymupdf.open(view_pdf_path(source)) as pdf:
            indices = list(range(len(pdf)))
            if preferred_page and 1 <= preferred_page <= len(pdf):
                indices.remove(preferred_page - 1)
                indices.insert(0, preferred_page - 1)
            for term in _search_terms(evidence):
                for index in indices:
                    page = pdf[index]
                    rectangles = page.search_for(term)
                    if not rectangles:
                        parts = [(word[4], pymupdf.Rect(word[:4]), (word[5], word[6])) for word in page.get_text("words", sort=True)]
                        rectangles = _matching_rects(parts, term, join_font_runs=True)
                    if rectangles:
                        return _location(index + 1, rectangles, page.rect.width, page.rect.height)
    # Scans and photos have no digital text layer. Reuse saved OCR coordinates;
    # no second OCR run and no estimated character positions on the image.
    pages = sorted((document_ir or {}).get("pages", []), key=lambda page: page.get("number") != preferred_page)
    for page in pages:
        if not page.get("width") or not page.get("height"):
            continue
        parts = [(block["text"], pymupdf.Rect(tuple(block["bbox"][key] for key in ("x0", "y0", "x1", "y1"))), index)
                 for index, block in enumerate(page.get("blocks", [])) if block.get("source") == "ocr" and block.get("bbox")]
        rectangles = _matching_rects(parts, evidence)
        if rectangles:
            return _location(page.get("number") or 1, rectangles, page["width"], page["height"])
    return None
