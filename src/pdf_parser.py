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
            blocks: list[BlockIR] = []

            raw_blocks = page.get_text(
                "blocks",
                sort=True,
            )

            for raw_block in raw_blocks:
                (
                    x0,
                    y0,
                    x1,
                    y1,
                    text,
                    block_number,
                    block_type,
                ) = raw_block

                text = text.strip()

                # block_type=0 означает текстовый блок.
                if block_type != 0 or not text:
                    continue

                block = BlockIR(
                    id=f"page-{page_number}-block-{block_number}",
                    kind=BlockKind.PARAGRAPH,
                    text=text,
                    source=BlockSource.DIGITAL,
                    bbox=BBox(
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                    ),
                )

                blocks.append(block)
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

