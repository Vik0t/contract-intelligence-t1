from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table

from src.document_ir import (
    BlockIR,
    BlockKind,
    BlockSource,
    DocumentIR,
    PageIR,
    SourceFormat,
)
from src.ocr import OCRBackend
from src.pdf_parser import parse_pdf


def parse_docx(file_path: str | Path) -> DocumentIR:
    """Преобразует DOCX в DocumentIR без попытки восстановить экранную пагинацию."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError("Ожидался DOCX-файл")

    document = Document(path)
    blocks: list[BlockIR] = []

    for order, item in enumerate(document.iter_inner_content()):
        if isinstance(item, Table):
            rows = [
                " | ".join(cell.text.strip() for cell in row.cells)
                for row in item.rows
            ]
            text = "\n".join(row for row in rows if row.strip(" |"))
            kind = BlockKind.TABLE
        else:
            text = item.text.strip()
            kind = BlockKind.PARAGRAPH

        if not text:
            continue

        blocks.append(
            BlockIR(
                id=f"docx-block-{order}",
                kind=kind,
                text=text,
                source=BlockSource.DOCX,
                order=order,
            )
        )

    return DocumentIR(
        source_format=SourceFormat.DOCX,
        source_path=str(path.resolve()),
        page_count=1,
        pages=[
            PageIR(
                number=1,
                blocks=blocks,
                needs_ocr=False,
            )
        ],
        warnings=[
            "DOCX не хранит надёжную физическую пагинацию; "
            "весь документ представлен как логическая страница 1"
        ],
    )


def parse_document(
    file_path: str | Path,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
) -> DocumentIR:
    """Маршрутизирует поддерживаемый файл в соответствующий DocumentIR-парсер."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return parse_pdf(path, ocr_backend=ocr_backend, ocr_dpi=ocr_dpi)
    if suffix == ".docx":
        return parse_docx(path)

    raise ValueError("Поддерживаются только PDF и DOCX")


def document_ir_to_text(
    document: DocumentIR,
    *,
    start_page: int = 1,
    max_pages: int | None = None,
) -> str:
    """Готовит единый текст с метками страниц для структурного извлечения."""
    if start_page < 1:
        raise ValueError("start_page должен быть не меньше 1")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages должен быть положительным")

    start_index = start_page - 1
    if start_index >= len(document.pages):
        raise ValueError(f"start_page должен быть от 1 до {len(document.pages)}")

    pages = document.pages[start_index:]
    if max_pages is not None:
        pages = pages[:max_pages]

    chunks: list[str] = []
    for page in pages:
        page_number = page.number or 1
        chunks.append(f"PAGE {page_number}")

        ocr_blocks = [
            block for block in page.blocks if block.source == BlockSource.OCR
        ]
        # На OCR-странице распознанный слой обычно содержит всю страницу.
        # DIGITAL-блоки остаются в IR для аудита, но не дублируются в тексте модели.
        selected = ocr_blocks if page.needs_ocr and ocr_blocks else page.blocks
        selected = sorted(selected, key=_reading_order)
        chunks.extend(block.text for block in selected)

    text = "\n\n".join(chunk for chunk in chunks if chunk.strip()).strip()
    if not text:
        raise ValueError("Документ не содержит текста для извлечения")
    return text


def _reading_order(block: BlockIR) -> tuple[float, float, float]:
    if block.order is not None:
        return (0, float(block.order), 0)
    if block.bbox is not None:
        return (1, block.bbox.y0, block.bbox.x0)
    return (2, 0, 0)


# Совместимое имя для старых вызовов проекта.
parse_file = parse_document
