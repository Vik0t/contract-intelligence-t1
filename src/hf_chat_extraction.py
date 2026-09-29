"""Fallback field extraction through Hugging Face's hosted chat API."""

from __future__ import annotations

import json
from typing import Any

from src.document_ir import DocumentIR
from src.extraction.pipeline import parse_json_output
from src.extraction.postprocess import postprocess_extraction, validate_extraction
from src.extraction.schema import CONTRACT_TEMPLATE, INSTRUCTIONS
from src.extraction.summary import generate_chat
from src.hf_space_extraction import build_retrieved_context


def extract_fields_with_hf_chat(
    text: str,
    document_ir: DocumentIR | None = None,
    *,
    model: str,
    context_chars: int = 3000,
    max_tokens: int = 2500,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Return the same field structure as NuExtract when its Space is unavailable."""
    context = build_retrieved_context(text, max_chars=context_chars)
    if not context.strip():
        context = text[:context_chars]
    prompt = (
        f"{INSTRUCTIONS}\n\n"
        "Верни только один JSON-объект по шаблону ниже. Вместо описаний типов "
        "подставь значение или null. Для каждой цитаты укажи страницу PAGE N. "
        "Не добавляй пояснений и не используй Markdown.\n\n"
        f"Шаблон:\n{json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False)}\n\n"
        f"Фрагменты документа:\n{context}"
    )
    raw = generate_chat(
        prompt, model=model, max_tokens=max_tokens, temperature=0.0, provider="hf"
    )
    parsed = parse_json_output(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Hugging Face API не вернул объект с полями договора")
    if not any(key in parsed for key in CONTRACT_TEMPLATE):
        raise ValueError("Hugging Face API не вернул поля договора")
    result = postprocess_extraction(parsed, text)
    if document_ir is not None:
        result = validate_extraction(result, document_ir)
    prompt_tokens = len(prompt.split())
    completion_tokens = len(raw.split())
    return result, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
