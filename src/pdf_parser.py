from pathlib import Path

import pymupdf
from src.ocr import OCRBackend, render_pdf_page
from src.document_ir import (
    BBox,
    BlockIR,
    BlockKind,
    BlockSource,
    DocumentIR,
    PageIR,
    SourceFormat,
)

MIN_DIGITAL_TEXT_CHARS = 30


def _digital_blocks(page: pymupdf.Page, number: int) -> list[BlockIR]:
    # A PDF paragraph can consist of separate font runs whose internal order is
    # unrelated to reading order (notably DOCX exported by LibreOffice).
    lines: list[list[tuple]] = []
    for word in page.get_text("words", sort=True):
        if not lines:
            lines.append([word])
            continue
        previous = lines[-1][-1]
        same_line = abs((word[1] + word[3]) / 2 - (previous[1] + previous[3]) / 2) < max(word[3] - word[1], previous[3] - previous[1]) * 0.5
        if same_line and word[0] >= previous[0]:
            lines[-1].append(word)
        else:
            lines.append([word])
    blocks = []
    for index, words in enumerate(lines):
        text = ""
        previous = None
        for word in words:
            # Join adjacent font runs, preserving spaces between real words.
            gap = word[0] - previous[2] if previous else 0
            separator = " " if previous and gap > max(word[3] - word[1], previous[3] - previous[1]) * 0.08 else ""
            text += separator + word[4]
            previous = word
        text = text.replace("\u00a0", " ").replace("\u00ad", "-").strip()
        if text:
            blocks.append(BlockIR(
                id=f"page-{number}-line-{index}", kind=BlockKind.PARAGRAPH,
                text=text, source=BlockSource.DIGITAL, order=index,
                bbox=BBox(x0=max(0, min(word[0] for word in words)), y0=max(0, min(word[1] for word in words)),
                          x1=max(word[2] for word in words), y1=max(word[3] for word in words)),
            ))
    return blocks

def parse_pdf(
    file_path: str | Path,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
) -> DocumentIR:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError("Ожидался PDF-файл")

    pages: list[PageIR] = []
    warnings: list[str] = []

    with pymupdf.open(path) as pdf:
        page_count = len(pdf)

        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            blocks = _digital_blocks(page, page_number)
            text_length = sum(len(block.text) for block in blocks)
            needs_ocr = text_length < MIN_DIGITAL_TEXT_CHARS

            if needs_ocr:
                if ocr_backend is None:
                    warnings.append(
                        f"Страница {page_number}: требуется OCR, "
                        "но OCR backend не передан"
                    )
                else:
                    image = render_pdf_page(
                        page,
                        dpi=ocr_dpi,
                    )

                    ocr_blocks = ocr_backend.extract_blocks(
                        image,
                        page_number=page_number,
                        page_width=page.rect.width,
                        page_height=page.rect.height,
                    )

                    if ocr_blocks:
                        # Не выбрасываем короткий, но точный цифровой слой:
                        # OCR дополняет уже извлечённые DIGITAL-блоки.
                        blocks.extend(ocr_blocks)
                    else:
                        warnings.append(
                            f"Страница {page_number}: OCR не вернул текст"
                        )
            page_ir = PageIR(
                number=page_number,
                width=page.rect.width,
                height=page.rect.height,
                blocks=blocks,
                needs_ocr=needs_ocr,
            )

            pages.append(page_ir)

    return DocumentIR(
        source_format=SourceFormat.PDF,
        source_path=str(path.resolve()),
        page_count=page_count,
        pages=pages,
        warnings=warnings,
    )

