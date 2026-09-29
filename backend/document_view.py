"""Render uploaded documents and locate evidence on their real pages."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

import pymupdf


_conversion_lock = threading.Lock()


class ViewUnavailable(RuntimeError):
    pass


def view_pdf_path(source: str | Path) -> Path:
    path = Path(source)
    if path.suffix.lower() == ".pdf":
        return path
    if path.suffix.lower() != ".docx":
        raise ViewUnavailable("Для этого формата просмотр страниц недоступен")
    configured = os.getenv("LIBREOFFICE_BIN", "").strip()
    converter = configured if configured and Path(configured).is_file() else shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise ViewUnavailable("Для просмотра DOCX с оформлением нужен LibreOffice на сервере")

    rendered = path.with_name(path.name + ".rendered.pdf")
    with _conversion_lock:
        if rendered.exists() and rendered.stat().st_mtime_ns >= path.stat().st_mtime_ns:
            return rendered
        with tempfile.TemporaryDirectory(prefix="contract-view-") as directory:
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


def render_page(source: str | Path, number: int) -> bytes:
    with pymupdf.open(view_pdf_path(source)) as pdf:
        if number < 1 or number > len(pdf):
            raise IndexError("Страница не найдена")
        page = pdf[number - 1]
        scale = min(2.0, 1400 / max(page.rect.width, 1))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")


def page_count(source: str | Path) -> int:
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


def locate_evidence(source: str | Path, evidence: str, preferred_page: int | None = None) -> dict | None:
    if not evidence or not evidence.strip():
        return None
    with pymupdf.open(view_pdf_path(source)) as pdf:
        indices = list(range(len(pdf)))
        if preferred_page and 1 <= preferred_page <= len(pdf):
            indices.remove(preferred_page - 1)
            indices.insert(0, preferred_page - 1)
        for term in _search_terms(evidence):
            for index in indices:
                page = pdf[index]
                rectangles = page.search_for(term)
                if rectangles:
                    return {
                        "page": index + 1,
                        "rects": [
                            {
                                "x": rect.x0 / page.rect.width,
                                "y": rect.y0 / page.rect.height,
                                "width": rect.width / page.rect.width,
                                "height": rect.height / page.rect.height,
                            }
                            for rect in rectangles[:12]
                        ],
                    }
    return None
