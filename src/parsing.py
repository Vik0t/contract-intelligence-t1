from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from docx import Document
from docx.table import Table
from PIL import Image, ImageOps

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


def normalize_document_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(c for c in text if c in "\n\t" or not unicodedata.category(c).startswith("C"))
    text = text.replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = text.translate(str.maketrans({"“": '"', "”": '"', "«": '"', "»": '"', "–": "-", "—": "-", "\u00a0": " "}))
    text = re.sub(r"\bN[oо]\.?\s*(?=\d)", "№ ", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip() and not all(unicodedata.category(c).startswith("C") for c in line)).strip()


def parse_docx(file_path: str | Path) -> DocumentIR:
    """Преобразует DOCX в DocumentIR без попытки восстановить экранную пагинацию."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError("Ожидался DOCX-файл")

    document = Document(path)
    blocks: list[BlockIR] = []

    seen_parts = set()

    def append_item(item, kind=None):
        if isinstance(item, Table):
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in item.rows]
            text = "\n".join(row for row in rows if row.strip(" |"))
            block_kind = kind or BlockKind.TABLE
        else:
            text = item.text.strip()
            block_kind = kind or BlockKind.PARAGRAPH
        text = normalize_document_text(text)
        if text:
            blocks.append(BlockIR(id=f"docx-block-{len(blocks)}", kind=block_kind,
                                  text=text, source=BlockSource.DOCX, order=len(blocks)))

    def append_margin(margin, kind):
        if margin.part.partname in seen_parts:
            return
        seen_parts.add(margin.part.partname)
        for item in margin.iter_inner_content():
            append_item(item, kind)

    for section in document.sections:
        for header in (section.header, section.first_page_header, section.even_page_header):
            append_margin(header, BlockKind.HEADER)

    for item in document.iter_inner_content():
        append_item(item)
    for section in document.sections:
        for footer in (section.footer, section.first_page_footer, section.even_page_footer):
            append_margin(footer, BlockKind.FOOTER)

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


def parse_image(
    file_path: str | Path,
    *,
    ocr_backend: OCRBackend | None = None,
) -> DocumentIR:
    """Преобразует фотографию документа в одностраничный DocumentIR."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Ожидалось изображение JPG или PNG")

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size

    warnings: list[str] = []
    blocks: list[BlockIR] = []
    if ocr_backend is None:
        warnings.append("Фотография требует распознавания текста, но OCR недоступен")
    else:
        blocks = ocr_backend.extract_blocks(
            image,
            page_number=1,
            page_width=float(width),
            page_height=float(height),
        )
        if not blocks:
            warnings.append("На фотографии не удалось распознать текст")

    return DocumentIR(
        source_format=SourceFormat.IMAGE,
        source_path=str(path.resolve()),
        page_count=1,
        pages=[
            PageIR(
                number=1,
                width=float(width),
                height=float(height),
                image_ref=str(path.resolve()),
                blocks=blocks,
                needs_ocr=True,
            )
        ],
        warnings=warnings,
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
        parsed = parse_pdf(path, ocr_backend=ocr_backend, ocr_dpi=ocr_dpi)
        for page in parsed.pages:
            for block in page.blocks:
                block.text = normalize_document_text(block.text) or block.text
        return parsed
    if suffix == ".docx":
        return parse_docx(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return parse_image(path, ocr_backend=ocr_backend)

    raise ValueError("Поддерживаются PDF, DOCX, JPG и PNG")


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
    has_text = False
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
        has_text = has_text or any(block.text.strip() for block in selected)
        chunks.extend(block.text for block in selected)

    text = "\n\n".join(chunk for chunk in chunks if chunk.strip()).strip()
    if not has_text:
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
