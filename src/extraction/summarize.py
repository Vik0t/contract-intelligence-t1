# надо создать токен на huggingface 

from __future__ import annotations

import logging
import os
from typing import Any

from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv() 

logger = logging.getLogger(__name__)

SUMMARY_MODEL_NAME = os.environ.get(
    "SUMMARY_MODEL_NAME",
    "Qwen/Qwen2.5-7B-Instruct:featherless-ai",
)

# Сколько символов документа максимум отправляем в модель.
SUMMARY_MAX_INPUT_CHARS = int(os.environ.get("SUMMARY_MAX_INPUT_CHARS", "4000"))

# Сколько токенов модель может сгенерировать в ответе.
SUMMARY_MAX_NEW_TOKENS = int(os.environ.get("SUMMARY_MAX_NEW_TOKENS", "300"))


SUMMARY_PROMPT_TEMPLATE = """Ты — русскоязычный юридический ассистент. Твоя задача — кратко описать суть договора.

Извлечённые поля документа:
{fields_block}

Текст документа (может быть обрезан):
{document_text}

Задача: сформулируй 5 предложений на русском, которые ясно объясняют,
о чём этот договор — предмет договора, кто стороны, ключевая сумма/условие,
срок действия. Используй ТОЛЬКО РУССКИЙ язык.
Опирайся в первую очередь на извлечённые поля (они уже проверены),
текст используй только как дополнительный контекст.
Не придумывай факты, которых нет ни в полях, ни в тексте.
Ответь только текстом summary, без вступлений вроде "Вот summary:".
"""


def _get_client() -> InferenceClient:
    """Создаёт InferenceClient с токеном из окружения.

    Модель передаётся не здесь, а в chat.completions.create(...), чтобы
    можно было менять её без пересоздания клиента.
    """
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "Не найден HF_TOKEN в переменных окружения. "
            "Создай токен на https://huggingface.co/settings/tokens "
            "и добавь его в .env как HF_TOKEN=..."
        )
    return InferenceClient(token=token)


def _format_fields_block(extracted_fields: dict[str, Any]) -> str:
    """Превращает словарь извлечённых полей в читаемый для модели текст."""
    if not extracted_fields:
        return "(поля не извлечены)"

    lines: list[str] = []
    for key, value in extracted_fields.items():
        if value in (None, "", []):
            continue
        if isinstance(value, (dict, list)):
            import json
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")

    return "\n".join(lines) if lines else "(поля не извлечены)"


def summarize_document(
    document_text: str,
    extracted_fields: dict[str, Any],
    max_input_chars: int | None = None,
    max_new_tokens: int | None = None,
) -> str:
    """Генерирует краткое summary документа на основе текста и извлечённых полей.

    Args:
        document_text: исходный текст контракта (после парсинга PDF/DOCX/PNG).
            Может быть пустой строкой, если суммаризация строится только
            по извлечённым полям.
        extracted_fields: словарь с уже извлечёнными полями
            (номер контракта, стороны, суммы, VAT и т.д.) из pipeline.py.
        max_input_chars: обрезка текста документа, чтобы не раздувать
            промпт и не упираться в лимиты API.
            По умолчанию — SUMMARY_MAX_INPUT_CHARS из .env или 4000.
        max_new_tokens: лимит длины сгенерированного summary.
            По умолчанию — SUMMARY_MAX_NEW_TOKENS из .env или 300.

    Returns:
        Строка с 4-5 предложениями summary на русском.

    Raises:
        RuntimeError: если HF_TOKEN не задан в окружении.
        huggingface_hub.errors.BadRequestError: если модель/провайдер
            недоступны или запрос некорректен.
    """
    if max_input_chars is None:
        max_input_chars = SUMMARY_MAX_INPUT_CHARS
    if max_new_tokens is None:
        max_new_tokens = SUMMARY_MAX_NEW_TOKENS

    client = _get_client()

    truncated_text = (document_text or "")[:max_input_chars]
    fields_block = _format_fields_block(extracted_fields)

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        fields_block=fields_block,
        document_text=truncated_text or "(текст не передан)",
    )

    logger.debug(
        "Summarize request: model=%s, prompt_chars=%d, max_new_tokens=%d",
        SUMMARY_MODEL_NAME,
        len(prompt),
        max_new_tokens,
    )

    response = client.chat.completions.create(
        model=SUMMARY_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_new_tokens,
        temperature=0.5,
    )

    if not response.choices:
        raise RuntimeError(
            f"HF Inference вернул пустой choices для модели {SUMMARY_MODEL_NAME}"
        )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError(
            f"HF Inference вернул пустой content для модели {SUMMARY_MODEL_NAME}"
        )

    return content.strip()


# def smoke_test() -> None:
#     """Быстрая проверка: отвечает ли SUMMARY_MODEL_NAME."""
#     client = _get_client()
#     try:
#         r = client.chat.completions.create(
#             model=SUMMARY_MODEL_NAME,
#             messages=[{"role": "user", "content": "Ответь одним словом: работает?"}],
#             max_tokens=20,
#             temperature=0.0,
#         )
#         print(f"OK   {SUMMARY_MODEL_NAME} → {r.choices[0].message.content!r}")
#     except Exception as exc:
#         print(f"FAIL {SUMMARY_MODEL_NAME} → {type(exc).__name__}: {exc}")
#         raise


# if __name__ == "__main__":
#     # uv run python -m src.extraction.summarize
#     smoke_test()