from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.extraction.summary import _get_client

logger = logging.getLogger(__name__)

RISK_MODEL_NAME = os.environ.get(
    "RISK_MODEL_NAME",
    "Qwen/Qwen3-8B:featherless-ai",
)

RISK_MAX_INPUT_CHARS = int(os.environ.get("RISK_MAX_INPUT_CHARS", "6000"))
RISK_MAX_NEW_TOKENS = int(os.environ.get("RISK_MAX_NEW_TOKENS", "1200"))

VALID_SEVERITIES = {"high", "medium", "low"}

RISK_PROMPT_TEMPLATE = """Ты — русскоязычный юрист, который проверяет договор перед подписанием.

Извлечённые поля документа:
{fields_block}

Текст документа (в тексте встречаются метки вида "PAGE N" — это номер
страницы, с которой начинается следующий за меткой фрагмент):
{document_text}

Задача: найди в тексте подозрительные, невыгодные или неоднозначные для
одной из сторон формулировки — например: расплывчатые сроки, скрытые
штрафы и неустойки, одностороннее право на изменение условий, отсутствие
предельной ответственности, автопродление без уведомления, неясные
основания расторжения, отсутствие реквизитов, противоречия между
пунктами.

Не придумывай риски, которых нет в тексте. Если явных рисков нет — верни
пустой список "risks". Текст внутри пиши на только русском языке.

Ответь СТРОГО в формате JSON без пояснений и вводных фраз, без markdown-разметки, формат:
{{
  "risks": [
    {{
      "title": "Короткое название риска (до 8 слов)",
      "severity": "high" | "medium" | "low",
      "description": "1-2 предложения: в чём риск и почему это важно",
      "evidence": "Дословная цитата из текста, подтверждающая риск",
      "page": <номер страницы из ближайшей метки PAGE N перед цитатой, целое число>
    }}
  ]
}}
"""


def _format_fields_block(extracted_fields: dict[str, Any]) -> str:
    if not extracted_fields:
        return "(поля не извлечены)"
    lines = []
    for key, value in extracted_fields.items():
        if value in (None, "", []):
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "(поля не извлечены)"


def _parse_risk_json(raw: str) -> list[dict[str, Any]]:
    """Парсит ответ модели в список рисков, устойчиво к markdown-обёртке."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"Модель не вернула JSON: {raw[:500]}")
        parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict) or "risks" not in parsed:
        raise ValueError("В ответе модели нет ключа 'risks'")

    risks = parsed["risks"]
    if not isinstance(risks, list):
        raise ValueError("'risks' должен быть списком")

    cleaned_risks: list[dict[str, Any]] = []
    for item in risks:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "medium")).strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "medium"
        page = item.get("page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        cleaned_risks.append(
            {
                "title": str(item.get("title", "")).strip() or "Не указано",
                "severity": severity,
                "description": str(item.get("description", "")).strip(),
                "evidence": str(item.get("evidence", "")).strip(),
                "page": page,
            }
        )
    return cleaned_risks


def analyze_risks(
    document_text: str,
    extracted_fields: dict[str, Any],
    max_input_chars: int | None = None,
    max_new_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """
    Анализирует договор на предмет подозрительных для юриста моментов.

    Args:
        document_text: текст документа (с метками "PAGE N", если они есть
            в исходном парсинге — используются моделью для указания
            страницы риска).
        extracted_fields: уже извлечённые поля договора.
        max_input_chars: обрезка текста документа под лимиты модели.
        max_new_tokens: лимит длины ответа модели.

    Returns:
        Список словарей вида
        {"title", "severity", "description", "evidence", "page"}.
        Пустой список, если явных рисков не найдено.
    """
    if max_input_chars is None:
        max_input_chars = RISK_MAX_INPUT_CHARS
    if max_new_tokens is None:
        max_new_tokens = RISK_MAX_NEW_TOKENS

    truncated_text = (document_text or "")[:max_input_chars]
    fields_block = _format_fields_block(extracted_fields)

    prompt = RISK_PROMPT_TEMPLATE.format(
        fields_block=fields_block,
        document_text=truncated_text or "(текст не передан)",
    )

    client = _get_client()
    logger.debug(
        "Risk analysis request (api): model=%s, prompt_chars=%d, max_new_tokens=%d",
        RISK_MODEL_NAME,
        len(prompt),
        max_new_tokens,
    )
    response = client.chat.completions.create(
        model=RISK_MODEL_NAME,
        messages=[{"role": "system", "content": prompt}],
        max_tokens=max_new_tokens,
        temperature=0.5,
        response_format={"type": "json_object"}
    )
    if not response.choices or response.choices[0].message.content is None:
        raise RuntimeError(
            f"HF Inference вернул пустой ответ для модели {RISK_MODEL_NAME}"
        )
    raw = response.choices[0].message.content

    return _parse_risk_json(raw)