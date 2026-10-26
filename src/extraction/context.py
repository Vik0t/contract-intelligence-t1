"""Split every page into bounded chunks without dropping the document's tail."""

from __future__ import annotations

import re

PAGE_MARKER = re.compile(r"^PAGE\s+(\d+)\s*$", re.MULTILINE)


def document_chunks(text: str, max_chars: int, *, overlap: int = 250) -> list[str]:
    if max_chars < 256:
        raise ValueError("Размер фрагмента должен быть не меньше 256 символов")
    if not 0 <= overlap < max_chars // 2:
        raise ValueError("Перекрытие должно быть меньше половины фрагмента")
    if not text or not text.strip():
        raise ValueError("Документ не содержит текста для анализа")
    markers = list(PAGE_MARKER.finditer(text))
    sections: list[tuple[str, str]] = []
    if not markers:
        sections.append(("", text))
    else:
        if text[:markers[0].start()].strip():
            sections.append(("", text[:markers[0].start()]))
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            sections.append((f"PAGE {marker.group(1)}\n", text[marker.end():end].strip()))
    fragments: list[str] = []
    for prefix, body in sections:
        capacity = max_chars - len(prefix)
        start = 0
        while start < len(body):
            end = min(start + capacity, len(body))
            # Prefer paragraph/word boundaries, but always make forward progress.
            if end < len(body):
                boundary = body.rfind("\n", start + capacity // 2, end)
                if boundary < 0:
                    boundary = body.rfind(" ", start + capacity // 2, end)
                if boundary > start:
                    end = boundary
            fragments.append(prefix + body[start:end])
            if end == len(body):
                break
            start = max(start + 1, end - overlap)
    if not fragments:
        raise ValueError("Документ содержит только номера страниц, без текста")
    chunks: list[str] = []
    for fragment in fragments:
        if chunks and len(chunks[-1]) + len(fragment) + 2 <= max_chars:
            chunks[-1] += "\n\n" + fragment
        else:
            chunks.append(fragment)
    return chunks


def evidence_pages(text: str, evidence: str) -> list[int]:
    normalize = lambda value: " ".join(value.casefold().split())
    needle = normalize(evidence)
    if not needle:
        return []
    markers = list(PAGE_MARKER.finditer(text))
    return [
        int(marker.group(1))
        for index, marker in enumerate(markers)
        if needle in normalize(text[marker.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)])
    ]
