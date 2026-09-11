import os
import shutil
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import pymupdf
import pytesseract
from PIL import Image

from src.document_ir import BBox, BlockIR, BlockKind, BlockSource


class OCRBackend(Protocol):
    def extract_blocks(
        self,
        image: Image.Image,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> list[BlockIR]:
        """Возвращает OCR-блоки одной страницы.

        ``bbox`` возвращаемых блоков должен быть задан в координатах
        исходной PDF-страницы:

        - ``0 <= x <= page_width``;
        - ``0 <= y <= page_height``.

        Если OCR работает в пикселях отрендеренного изображения, backend
        должен самостоятельно преобразовать их в координаты PDF-страницы.
        """
        ...


class TesseractOCRBackend:
    """Локальный OCR backend на Tesseract без промежуточных файлов."""

    def __init__(
        self,
        *,
        language: str = "rus+eng",
        config: str = "--oem 3 --psm 3",
        min_confidence: float = 20,
        tesseract_cmd: str | Path | None = None,
        image_to_data: Callable[..., Mapping[str, Sequence[Any]]] | None = None,
    ) -> None:
        if not 0 <= min_confidence <= 100:
            raise ValueError("min_confidence должен быть от 0 до 100")

        self.language = language
        self.config = config
        self.min_confidence = min_confidence
        self._tesseract_cmd = Path(tesseract_cmd) if tesseract_cmd else None
        self._image_to_data = image_to_data

    def _configure_executable(self) -> None:
        if self._image_to_data is not None:
            return

        candidates = [
            self._tesseract_cmd,
            Path(os.environ["TESSERACT_CMD"])
            if os.environ.get("TESSERACT_CMD")
            else None,
            Path(found) if (found := shutil.which("tesseract")) else None,
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        executable = next(
            (candidate for candidate in candidates if candidate and candidate.is_file()),
            None,
        )
        if executable is None:
            raise RuntimeError(
                "Tesseract не найден. Установите Tesseract OCR с русским языком "
                "или задайте путь через переменную TESSERACT_CMD."
            )

        pytesseract.pytesseract.tesseract_cmd = str(executable)

    def extract_blocks(
        self,
        image: Image.Image,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> list[BlockIR]:
        self._configure_executable()
        image_to_data = self._image_to_data or pytesseract.image_to_data

        try:
            data = image_to_data(
                image.convert("RGB"),
                lang=self.language,
                config=self.config,
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractError as exc:
            raise RuntimeError(
                f"Tesseract не смог распознать страницу {page_number}. "
                f"Проверьте, что установлены языки: {self.language}"
            ) from exc

        required = {"text", "conf", "left", "top", "width", "height"}
        if not required.issubset(data):
            missing = ", ".join(sorted(required - set(data)))
            raise ValueError(f"Tesseract не вернул обязательные поля: {missing}")

        image_width, image_height = image.size
        scale_x = page_width / image_width
        scale_y = page_height / image_height
        groups: dict[tuple[int, int], list[int]] = defaultdict(list)

        item_count = len(data["text"])
        for index in range(item_count):
            text = str(data["text"][index]).strip()
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1
            if not text or confidence < self.min_confidence:
                continue

            block_number = _int_at(data, "block_num", index, default=0)
            paragraph_number = _int_at(data, "par_num", index, default=0)
            groups[(block_number, paragraph_number)].append(index)

        blocks: list[BlockIR] = []
        for order, ((block_number, paragraph_number), indices) in enumerate(groups.items()):
            text = " ".join(str(data["text"][index]).strip() for index in indices)
            left = min(float(data["left"][index]) for index in indices)
            top = min(float(data["top"][index]) for index in indices)
            right = max(
                float(data["left"][index]) + float(data["width"][index])
                for index in indices
            )
            bottom = max(
                float(data["top"][index]) + float(data["height"][index])
                for index in indices
            )
            confidence = sum(float(data["conf"][index]) for index in indices) / (
                100 * len(indices)
            )

            if right <= left or bottom <= top:
                continue

            blocks.append(
                BlockIR(
                    id=(
                        f"page-{page_number}-tesseract-"
                        f"{block_number}-{paragraph_number}"
                    ),
                    kind=BlockKind.PARAGRAPH,
                    text=text,
                    source=BlockSource.OCR,
                    bbox=BBox(
                        x0=max(0, left * scale_x),
                        y0=max(0, top * scale_y),
                        x1=min(page_width, right * scale_x),
                        y1=min(page_height, bottom * scale_y),
                    ),
                    confidence=max(0, min(1, confidence)),
                    raw_label="tesseract_paragraph",
                    order=order,
                )
            )

        return blocks


def _int_at(
    data: Mapping[str, Sequence[Any]],
    key: str,
    index: int,
    *,
    default: int,
) -> int:
    values = data.get(key)
    if values is None:
        return default
    try:
        return int(values[index])
    except (IndexError, TypeError, ValueError):
        return default


def render_pdf_page(
    page: pymupdf.Page,
    *,
    dpi: int = 200,
) -> Image.Image:
    pixmap = page.get_pixmap(
        dpi=dpi,
        alpha=False,
    )

    return Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )
