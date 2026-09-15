from __future__ import annotations

from pathlib import Path
from typing import Any

from src.document_ir import DocumentIR
from src.ocr import OCRBackend
from src.extraction.pipeline import extract_text_from_document
from src.hf_space_extraction import (
    DEFAULT_SPACE_ID,
    HFSpaceNuExtractBackend,
)


def extract_contract_key_data_hf_space(
    document: str | Path | DocumentIR,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
    start_page: int = 1,
    max_pages: int | None = None,
    space_id: str = DEFAULT_SPACE_ID,
    prompt_mode: str = "compact",
    context_mode: str = "retrieved",
    context_chars: int = 3000,
    temperature: float = 0.0,
    reasoning: bool = False,
    connect_timeout: float = 300.0,
    backend: HFSpaceNuExtractBackend | None = None,
) -> dict[str, Any]:
    """Извлекает реквизиты договора через публичный HF Space NuExtract3.

    Сигнатура намеренно похожа на extract_contract_key_data(), чтобы можно
    было подменять бэкенд в evaluate-скрипте по флагу --backend.

    connect_timeout: таймаут (сек) для httpx-клиента gradio_client. Это же
    значение действует и на ожидание ответа (read timeout), а не только на
    установку соединения — публичный Space без GPU может генерировать
    заметно дольше 30 сек, отсюда увеличенный дефолт.

    backend: можно передать уже созданный HFSpaceNuExtractBackend, чтобы не
    пересоздавать gradio_client.Client на каждый документ в цикле оценки.

    Returns:
        dict: извлечённые поля (совместимо по форме с локальным бэкендом).
    """
    text, document_ir = extract_text_from_document(
        document,
        ocr_backend=ocr_backend,
        ocr_dpi=ocr_dpi,
        start_page=start_page,
        max_pages=max_pages,
    )

    if backend is None:
        backend = HFSpaceNuExtractBackend(space_id=space_id, connect_timeout=connect_timeout)

    extraction = backend.extract_fields_from_text(
        text,
        document_ir,
        prompt_mode=prompt_mode,
        context_mode=context_mode,
        context_chars=context_chars,
        temperature=temperature,
        reasoning=reasoning,
    )

    return extraction.result