from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PIL import Image

from src.document_ir import BBox, BlockIR, BlockKind, BlockSource


def paddle_label_to_kind(label: str) -> BlockKind:
    """Сводит подробные PaddleOCR-VL labels к компактным типам DocumentIR."""
    normalized = label.strip().lower()

    if "table" in normalized:
        return BlockKind.TABLE
    if "header" in normalized:
        return BlockKind.HEADER
    if "footer" in normalized or "footnote" in normalized:
        return BlockKind.FOOTER
    return BlockKind.PARAGRAPH


def paddle_result_to_blocks(
    parsing_results: Sequence[Mapping[str, Any]],
    *,
    page_number: int,
    image_width: int,
    image_height: int,
    page_width: float,
    page_height: float,
) -> list[BlockIR]:
    """Преобразует PaddleOCR-VL ``parsing_res_list`` в OCR-блоки DocumentIR."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Размеры изображения должны быть положительными")
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Размеры PDF-страницы должны быть положительными")

    scale_x = page_width / image_width
    scale_y = page_height / image_height
    ordered_results = sorted(
        enumerate(parsing_results),
        key=lambda pair: (
            pair[1].get("block_order") is None,
            pair[1].get("block_order")
            if pair[1].get("block_order") is not None
            else pair[0],
        ),
    )

    blocks: list[BlockIR] = []
    for fallback_order, item in ordered_results:
        text = str(item.get("block_content") or "").strip()
        if not text:
            continue

        raw_bbox = item.get("block_bbox")
        if raw_bbox is None:
            bbox = None
        else:
            coordinates = list(raw_bbox)
            if len(coordinates) != 4:
                raise ValueError(
                    "PaddleOCR-VL block_bbox должен содержать 4 координаты; "
                    "используйте layout_shape_mode='rect'"
                )

            pixel_x0, pixel_y0, pixel_x1, pixel_y1 = map(float, coordinates)
            pixel_x0 = min(max(pixel_x0, 0.0), float(image_width))
            pixel_y0 = min(max(pixel_y0, 0.0), float(image_height))
            pixel_x1 = min(max(pixel_x1, 0.0), float(image_width))
            pixel_y1 = min(max(pixel_y1, 0.0), float(image_height))
            bbox = BBox(
                x0=pixel_x0 * scale_x,
                y0=pixel_y0 * scale_y,
                x1=pixel_x1 * scale_x,
                y1=pixel_y1 * scale_y,
            )

        raw_label = str(item.get("block_label") or "text")
        raw_order = item.get("block_order")
        order = int(raw_order) if raw_order is not None else fallback_order
        raw_block_id = item.get("block_id", order)

        blocks.append(
            BlockIR(
                id=f"page-{page_number}-paddle-{raw_block_id}",
                kind=paddle_label_to_kind(raw_label),
                text=text,
                source=BlockSource.OCR,
                bbox=bbox,
                confidence=None,
                raw_label=raw_label,
                order=order,
            )
        )

    return blocks


class PaddleOCRVLBackend:
    """Адаптер полного PaddleOCR-VL-1.6 pipeline к интерфейсу OCRBackend."""

    def __init__(
        self,
        *,
        pipeline: Any | None = None,
        device: str | None = None,
    ) -> None:
        if pipeline is None:
            try:
                from paddleocr import PaddleOCRVL
            except ImportError as exc:
                raise RuntimeError(
                    "PaddleOCR не установлен. Установите PaddleOCR-VL "
                    "в совместимое отдельное окружение."
                ) from exc

            options: dict[str, Any] = {
                "pipeline_version": "v1.6",
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_layout_detection": True,
            }
            if device is not None:
                options["device"] = device
            pipeline = PaddleOCRVL(**options)

        self._pipeline = pipeline

    def extract_blocks(
        self,
        image: Image.Image,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> list[BlockIR]:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "Для PaddleOCRVLBackend требуется NumPy"
            ) from exc

        rgb_image = image.convert("RGB")
        output = self._pipeline.predict(
            np.asarray(rgb_image),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
            layout_shape_mode="rect",
            format_block_content=False,
        )

        parsing_results: list[Mapping[str, Any]] = []
        for result in output:
            payload = result.json
            if callable(payload):
                payload = payload()
            if not isinstance(payload, Mapping):
                raise TypeError("PaddleOCR-VL result.json должен быть словарём")

            result_data = payload.get("res", payload)
            if not isinstance(result_data, Mapping):
                raise TypeError("PaddleOCR-VL result['res'] должен быть словарём")

            raw_items = result_data.get("parsing_res_list", [])
            if not isinstance(raw_items, Sequence) or isinstance(
                raw_items, (str, bytes)
            ):
                raise TypeError(
                    "PaddleOCR-VL parsing_res_list должен быть списком"
                )
            parsing_results.extend(raw_items)

        return paddle_result_to_blocks(
            parsing_results,
            page_number=page_number,
            image_width=rgb_image.width,
            image_height=rgb_image.height,
            page_width=page_width,
            page_height=page_height,
        )
