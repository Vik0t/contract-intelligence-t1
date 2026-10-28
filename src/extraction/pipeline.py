from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import torch

from src.document_ir import DocumentIR
from src.ocr import OCRBackend, TesseractOCRBackend
from src.parsing import document_ir_to_text, parse_document

from src.extraction.schema import CONTRACT_TEMPLATE, INSTRUCTIONS
from src.extraction.model_loading import (
    load_model,
    use_mlx,
    record_usage,
    get_extraction_stats,
    _count_tokens_mlx,
    get_loaded_model_provenance,
)
from src.extraction.postprocess import postprocess_extraction, validate_extraction
from src.extraction.context import document_chunks
from src.extraction.validation import validate_model_result, merge_extractions


def build_messages(text: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        }
    ]


def parse_json_output(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Модель не вернула JSON")
        return json.loads(cleaned[start : end + 1])


def extract_text_from_document(
    document: str | Path | DocumentIR,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
    start_page: int = 1,
    max_pages: int | None = None,
) -> tuple[str, DocumentIR]:
    """Извлекает текст из документа и возвращает его вместе с DocumentIR.

    PDF сначала проходит разбор цифрового слоя. Tesseract вызывается только для
    страниц без достаточного текста.
    """
    if ocr_dpi <= 0:
        raise ValueError("ocr_dpi должен быть положительным")
    if start_page < 1:
        raise ValueError("start_page должен быть не меньше 1")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages должен быть не меньше 1")

    if isinstance(document, DocumentIR):
        document_ir = document
    else:
        backend = ocr_backend or TesseractOCRBackend()
        document_ir = parse_document(document, ocr_backend=backend, ocr_dpi=ocr_dpi)

    text = document_ir_to_text(document_ir, start_page=start_page, max_pages=max_pages)

    return text, document_ir


def extract_fields_from_text(
    text: str,
    document_ir: DocumentIR | None = None,
    *,
    thinking: bool = False,
    max_new_tokens: int = 2048,
    collect_stats: bool = True,
) -> dict[str, Any]:
    """Извлекает реквизиты из текста с помощью NuExtract3."""
    if max_new_tokens < 1:
        raise ValueError("max_new_tokens должен быть не меньше 1")

    prompt_tokens = 0
    completion_tokens = 0

    if use_mlx():
        from mlx_lm import generate as mlx_generate

        model, tokenizer = load_model()

        messages = build_messages(text)
        prompt = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=False,
            template=json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False, indent=2),
            instructions=INSTRUCTIONS,
            enable_thinking=thinking,
        )

        prompt_tokens = _count_tokens_mlx(tokenizer, prompt)

        raw = mlx_generate(model, tokenizer, prompt=prompt, max_tokens=max_new_tokens)

        completion_tokens = _count_tokens_mlx(tokenizer, raw)

        raw = raw.strip()

        try:
            parsed = parse_json_output(raw)
        except Exception as exc:
            raise ValueError("Модель вернула невалидный или незавершённый JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Модель вернула JSON, но не объект")

        parsed = postprocess_extraction(parsed, text)

        if document_ir is not None:
            parsed = validate_extraction(parsed, document_ir)
    else:
        processor, model = load_model()
        messages = build_messages(text)

        device = model.device

        inputs = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            template=json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False, indent=2),
            instructions=INSTRUCTIONS,
            enable_thinking=thinking,
        )

        prompt_tokens = inputs["input_ids"].shape[1]

        limit = getattr(getattr(model.config, "text_config", model.config), "max_position_embeddings", None)
        if limit and prompt_tokens + max_new_tokens > limit:
            raise ValueError("Фрагмент превышает контекст модели; уменьшите EXTRACTION_CHUNK_CHARS")
        inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}

        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated_ids = generated_ids[:, inputs["input_ids"].shape[1] :]

        completion_tokens = generated_ids.shape[1]

        raw = processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()

        try:
            parsed = parse_json_output(raw)
        except Exception as exc:
            raise ValueError("Модель вернула невалидный или незавершённый JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Модель вернула JSON, но не объект")

        parsed = postprocess_extraction(parsed, text)

        if document_ir is not None:
            parsed = validate_extraction(parsed, document_ir)

    if collect_stats:
        record_usage(prompt_tokens, completion_tokens)

    return validate_model_result(parsed, text)


def extract_contract_key_data(
    document: str | Path | DocumentIR | None = None,
    text: str | None = None,
    document_ir: DocumentIR | None = None,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
    start_page: int = 1,
    max_pages: int | None = None,
    thinking: bool = False,
    max_new_tokens: int = 2048,
    collect_stats: bool = True,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Извлекает реквизиты из PDF/DOCX или готового текста.

    Returns:
        tuple[dict, dict]: (extracted_data, token_usage)
    """
    if document is not None and text is not None:
        raise ValueError("Нельзя передавать одновременно document и text")

    if document is None and text is None:
        raise ValueError("Необходимо передать либо document, либо text")
    initial_usage = get_extraction_stats().copy()

    if document is not None:
        extracted_text, extracted_document_ir = extract_text_from_document(
            document,
            ocr_backend=ocr_backend,
            ocr_dpi=ocr_dpi,
            start_page=start_page,
            max_pages=max_pages,
        )
        text, document_ir = extracted_text, extracted_document_ir
    chunk_chars = int(os.getenv('EXTRACTION_CHUNK_CHARS', '12000'))
    chunks = document_chunks(text, chunk_chars)
    result = merge_extractions([
        extract_fields_from_text(
            chunk,
            document_ir,
            thinking=thinking,
            max_new_tokens=max_new_tokens,
            collect_stats=collect_stats,
        ) for chunk in chunks
    ], text, document_ir)
    result['_provenance'] = {**get_loaded_model_provenance(), 'instructions': INSTRUCTIONS,
                             'template': CONTRACT_TEMPLATE, 'messages': [build_messages(chunk) for chunk in chunks],
                             'parameters': {'max_new_tokens': max_new_tokens, 'thinking': thinking, 'chunk_chars': chunk_chars}}

    if collect_stats:
        return result, {key: value - initial_usage[key] for key, value in get_extraction_stats().items()}
    return result, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
