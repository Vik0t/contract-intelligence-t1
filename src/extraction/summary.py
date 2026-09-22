# надо создать токен на huggingface 

from __future__ import annotations

from functools import lru_cache
import logging
import os
from typing import Any
from openai import OpenAI
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv() 

logger = logging.getLogger(__name__)

# Переключатель бэкенда суммаризации
# "api" (по умолчанию) — вызов через HF Inference API
# "local" — загрузка модели на эту машину через transformers
client = OpenAI(
    base_url="https://deepcode.ci.nsu.ru/api/v1",
    api_key= os.environ.get("OPENROUTER_API_KEY")
)



SUMMARY_BACKEND_ENV = "SUMMARY_BACKEND"

SUMMARY_MODEL_NAME = os.environ.get(
    "SUMMARY_MODEL_NAME",
    "Qwen/Qwen2.5-7B-Instruct:featherless-ai",
)

# Модель для локального инференса 
SUMMARY_LOCAL_MODEL_NAME = os.environ.get(
    "SUMMARY_LOCAL_MODEL_NAME",
    "Qwen/Qwen2.5-3B-Instruct",
)

# Сколько символов документа максимум отправляем в модель.
SUMMARY_MAX_INPUT_CHARS = int(os.environ.get("SUMMARY_MAX_INPUT_CHARS", "4000"))

# Сколько токенов модель может сгенерировать в ответе.
SUMMARY_MAX_NEW_TOKENS = int(os.environ.get("SUMMARY_MAX_NEW_TOKENS", "300"))


def summary_backend() -> str:
    """Возвращает выбранный бэкенд суммаризации: 'api' или 'local'."""
    requested = os.getenv(SUMMARY_BACKEND_ENV, "api").strip().lower()
    if requested not in {"api", "local"}:
        raise ValueError(
            f"{SUMMARY_BACKEND_ENV} must be 'api' or 'local', got {requested!r}"
        )
    return requested


SUMMARY_PROMPT_TEMPLATE = """Ты — русскоязычный юридический ассистент. Твоя задача — кратко описать суть договора.

Извлечённые поля документа:
{fields_block}

Текст документа (может быть обрезан):
{document_text}

Задача: сформулируй 5-7 предложений на русском, которые ясно объясняют,
о чём этот договор — предмет договора, кто стороны, ключевая сумма,
срок действия и наиболее важные условия. Используй ТОЛЬКО РУССКИЙ язык, ДРУГИЕ ЗАПРЕЩЕНЫ.
Опирайся в первую очередь на извлечённые поля (они уже проверены),
текст используй как дополнительный контекст и источник информации об условиях.
Не придумывай факты, которых нет ни в полях, ни в тексте. Пиши грамматически и синтаксически правильно.
Ответь только текстом summary, без вступлений вроде "Вот summary:".
"""


def _get_client() -> InferenceClient:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "Не найден HF_TOKEN в переменных окружения. "
            "Создай токен на https://huggingface.co/settings/tokens "
            "и добавь его в .env как HF_TOKEN=..."
        )
    return InferenceClient(token=token)


@lru_cache(maxsize=1)
def _load_local_summary_model():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    logger.info("Loading local summary model: %s", SUMMARY_LOCAL_MODEL_NAME)

    tokenizer = AutoTokenizer.from_pretrained(SUMMARY_LOCAL_MODEL_NAME)

    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    elif torch.backends.mps.is_available():
        device = "mps"
        dtype = torch.float16
    else:
        device = "cpu"
        dtype = torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        SUMMARY_LOCAL_MODEL_NAME,
        dtype=dtype,
        device_map=device,
        low_cpu_mem_usage=True,
    ).eval()

    logger.info("Local summary model loaded on device=%s, dtype=%s", device, dtype)
    return model, tokenizer


def unload_local_summary_model() -> None:
    _load_local_summary_model.cache_clear()
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _summarize_local(prompt: str, max_new_tokens: int) -> str:
    import torch

    model, tokenizer = _load_local_summary_model()

    messages = [{"role": "user", "content": prompt}]
    input_ids = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    generated = output_ids[0][input_ids.shape[-1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def _format_fields_block(extracted_fields: dict[str, Any]) -> str:
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
        Строка с 5-7 предложениями summary на русском.

    Raises:
        RuntimeError: если HF_TOKEN не задан в окружении.
        huggingface_hub.errors.BadRequestError: если модель/провайдер
            недоступны или запрос некорректен.
    """
    if max_input_chars is None:
        max_input_chars = SUMMARY_MAX_INPUT_CHARS
    if max_new_tokens is None:
        max_new_tokens = SUMMARY_MAX_NEW_TOKENS

    truncated_text = (document_text or "")[:max_input_chars]
    fields_block = _format_fields_block(extracted_fields)

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        fields_block=fields_block,
        document_text=truncated_text or "(текст не передан)",
    )

    backend = summary_backend()

    if backend == "local":
        logger.debug(
            "Summarize request (local): model=%s, prompt_chars=%d, max_new_tokens=%d",
            SUMMARY_LOCAL_MODEL_NAME,
            len(prompt),
            max_new_tokens,
        )
        return _summarize_local(prompt, max_new_tokens)

    client = _get_client()

    logger.debug(
        "Summarize request (api): model=%s, prompt_chars=%d, max_new_tokens=%d",
        SUMMARY_MODEL_NAME,
        len(prompt),
        max_new_tokens,
    )

    response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V4-Flash-0731", 
    messages=[{"role": "system", "content": "напиши нгту шарага"}],
    max_tokens=max_new_tokens,
    temperature=0.4)

   
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