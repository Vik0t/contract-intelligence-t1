"""Evidence grounded contract risk review using the configured analysis API."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from src.extraction.summary import (
    DEFAULT_HF_FALLBACK_MODEL,
    _format_fields_block,
    generate_with_fallback,
)


RISK_PROMPT = """Ты помогаешь оператору предварительно проверить договор. Найди до 5 конкретных юридических или коммерческих рисков в тексте. Не считай отсутствие данных автоматически риском, если договор не требует этих условий. Не придумывай факты.
Верни только JSON-массив объектов с ключами title, body, evidence, page. title и body — кратко на русском. evidence — дословная короткая цитата из текста, подтверждающая риск. page — номер страницы из метки PAGE N, если он указан; иначе null. Если обоснованных рисков нет, верни [].

Извлечённые поля:
{fields}

Текст договора:
{text}
"""


def analyze_risks(document_text: str, extracted_fields: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = RISK_PROMPT.format(
        fields=_format_fields_block(extracted_fields),
        text=(document_text or "")[:int(os.getenv("RISK_MAX_INPUT_CHARS", "12000"))],
    )
    return generate_with_fallback(
        prompt,
        model=os.getenv("RISK_MODEL_NAME") or os.getenv("SUMMARY_MODEL_NAME", DEFAULT_HF_FALLBACK_MODEL),
        max_tokens=int(os.getenv("RISK_MAX_NEW_TOKENS", "900")),
        provider=os.getenv("RISK_PROVIDER") or os.getenv("SUMMARY_PROVIDER", "hf"),
        fallback_model=os.getenv("RISK_FALLBACK_MODEL_NAME", DEFAULT_HF_FALLBACK_MODEL),
        parse=lambda raw: parse_risks(raw, document_text),
    )


def parse_risks(raw: str, document_text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("API анализа рисков вернул некорректный формат")
    risks = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:160]
        body = str(item.get("body") or "").strip()[:700]
        evidence = str(item.get("evidence") or "").strip()[:1000]
        normalized_evidence = re.sub(r"\s+", " ", evidence).casefold()
        normalized_document = re.sub(r"\s+", " ", document_text or "").casefold()
        if title and body and evidence and normalized_evidence in normalized_document:
            page = item.get("page")
            risks.append({
                "title": title,
                "body": body,
                "evidence": evidence,
                "page": page if isinstance(page, int) and page > 0 else None,
            })
    if data and not risks:
        raise ValueError("API не вернул рисков с проверяемыми цитатами")
    return risks
