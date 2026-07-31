from pathlib import Path

import fitz
from PIL import Image

from src.document_ir import (
    BlockIR,
    BlockKind,
    BlockSource,
)
from src.ocr import TesseractOCRBackend
from src.paddle_ocr import (
    PaddleOCRVLBackend,
    paddle_result_to_blocks,
)
from src.pdf_parser import parse_pdf


class FakeOCRBackend:
    def __init__(self) -> None:
        self.called_pages: list[int] = []

    def extract_blocks(
        self,
        image,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> list[BlockIR]:
        self.called_pages.append(page_number)

        return [
            BlockIR(
                id=f"page-{page_number}-ocr-block-0",
                kind=BlockKind.PARAGRAPH,
                text="Распознанный текст сканированной страницы",
                source=BlockSource.OCR,
                bbox=None,
                confidence=0.95,
            )
        ]


def test_tesseract_result_is_mapped_to_document_ir() -> None:
    def fake_image_to_data(image, **kwargs):
        assert image.mode == "RGB"
        assert kwargs["lang"] == "rus+eng"
        return {
            "text": ["Договор", "поставки", "мусор"],
            "conf": ["96", "84", "5"],
            "left": [100, 300, 10],
            "top": [200, 200, 10],
            "width": [150, 180, 20],
            "height": [50, 50, 20],
            "block_num": [1, 1, 2],
            "par_num": [1, 1, 1],
        }

    backend = TesseractOCRBackend(image_to_data=fake_image_to_data)
    blocks = backend.extract_blocks(
        Image.new("RGB", (1000, 2000), "white"),
        page_number=2,
        page_width=500,
        page_height=1000,
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Договор поставки"
    assert blocks[0].source == BlockSource.OCR
    assert blocks[0].confidence == 0.9
    assert blocks[0].bbox is not None
    assert blocks[0].bbox.model_dump() == {
        "x0": 50.0,
        "y0": 100.0,
        "x1": 240.0,
        "y1": 125.0,
    }


class FakePaddleResult:
    def __init__(self, parsing_res_list: list[dict]) -> None:
        self.json = {
            "res": {
                "parsing_res_list": parsing_res_list,
            }
        }


class FakePaddlePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, ...], dict]] = []

    def predict(self, image, **kwargs):
        self.calls.append((image.shape, kwargs))
        return [
            FakePaddleResult(
                [
                    {
                        "block_bbox": [100, 200, 900, 300],
                        "block_label": "doc_title",
                        "block_content": "ДОГОВОР ПОСТАВКИ",
                        "block_id": 7,
                        "block_order": 0,
                    }
                ]
            )
        ]


def test_paddle_result_is_mapped_to_document_ir() -> None:
    blocks = paddle_result_to_blocks(
        [
            {
                "block_bbox": [100, 400, 900, 800],
                "block_label": "table",
                "block_content": "| Товар | Цена |",
                "block_id": 2,
                "block_order": 1,
            },
            {
                "block_bbox": [100, 200, 900, 300],
                "block_label": "doc_title",
                "block_content": "ДОГОВОР ПОСТАВКИ",
                "block_id": 1,
                "block_order": 0,
            },
        ],
        page_number=1,
        image_width=2000,
        image_height=3000,
        page_width=600,
        page_height=900,
    )

    assert [block.order for block in blocks] == [0, 1]
    assert blocks[0].kind == BlockKind.PARAGRAPH
    assert blocks[0].raw_label == "doc_title"
    assert blocks[0].source == BlockSource.OCR
    assert blocks[0].bbox is not None
    assert blocks[0].bbox.x0 == 30
    assert blocks[0].bbox.y0 == 60
    assert blocks[0].bbox.x1 == 270
    assert blocks[0].bbox.y1 == 90
    assert blocks[1].kind == BlockKind.TABLE


def test_paddle_backend_runs_only_for_ocr_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paddle-routing.pdf"
    create_test_pdf(pdf_path)
    pipeline = FakePaddlePipeline()
    backend = PaddleOCRVLBackend(pipeline=pipeline)

    document = parse_pdf(
        pdf_path,
        ocr_backend=backend,
    )

    assert len(pipeline.calls) == 1
    image_shape, options = pipeline.calls[0]
    assert image_shape[2] == 3
    assert options["layout_shape_mode"] == "rect"
    assert document.pages[0].blocks[0].source == BlockSource.OCR
    assert document.pages[0].blocks[0].raw_label == "doc_title"
    assert document.pages[1].blocks[0].source == BlockSource.DIGITAL
    assert document.warnings == []


def test_ocr_is_called_only_for_required_pages(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "routing.pdf"
    create_test_pdf(pdf_path)

    ocr_backend = FakeOCRBackend()

    document = parse_pdf(
        pdf_path,
        ocr_backend=ocr_backend,
    )

    blank_page = document.pages[0]
    digital_page = document.pages[1]

    # OCR вызван только для первой, пустой страницы.
    assert ocr_backend.called_pages == [1]

    assert blank_page.needs_ocr is True
    assert blank_page.blocks
    assert all(
        block.source == BlockSource.OCR
        for block in blank_page.blocks
    )

    assert digital_page.needs_ocr is False
    assert digital_page.blocks
    assert all(
        block.source == BlockSource.DIGITAL
        for block in digital_page.blocks
    )

    assert document.warnings == []


def test_ocr_preserves_short_digital_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "short-digital-text.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Short digital text")
    pdf.save(pdf_path)
    pdf.close()

    ocr_backend = FakeOCRBackend()
    document = parse_pdf(
        pdf_path,
        ocr_backend=ocr_backend,
    )

    page_ir = document.pages[0]
    sources = {block.source for block in page_ir.blocks}

    assert page_ir.needs_ocr is True
    assert ocr_backend.called_pages == [1]
    assert BlockSource.DIGITAL in sources
    assert BlockSource.OCR in sources
    assert document.warnings == []


def create_test_pdf(path: Path) -> None:
    pdf = fitz.open()

    # Страница без цифрового текста.
    pdf.new_page()

    # Страница с нормальным цифровым текстом.
    text_page = pdf.new_page()
    text_page.insert_text(
        (72, 72),
        "Договор поставки содержит достаточно цифрового текста",
    )

    pdf.save(path)
    pdf.close()


def test_pdf_pages_are_routed_to_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "routing.pdf"
    create_test_pdf(pdf_path)

    document = parse_pdf(pdf_path)

    assert document.page_count == 2
    assert len(document.pages) == 2

    blank_page = document.pages[0]
    digital_page = document.pages[1]

    assert blank_page.blocks == []
    assert blank_page.needs_ocr is True

    assert digital_page.blocks
    assert digital_page.needs_ocr is False

    assert all(
        block.source == BlockSource.DIGITAL
        for block in digital_page.blocks
    )
