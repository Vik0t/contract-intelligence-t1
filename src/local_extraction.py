from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

from src.document_ir import DocumentIR
from src.ocr import OCRBackend, TesseractOCRBackend
from src.parsing import document_ir_to_text, parse_document

MODEL_ID = "numind/NuExtract3"

# Структура шаблона совпадает со структурой ожидаемого JSON.
# verbatim-string просит модель возвращать текст дословно из документа.
CONTRACT_TEMPLATE: dict[str, Any] = {
    "contract_number": {
        "value": "verbatim-string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "contract_date": {
        "value": "date",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "contract_type": {
        "value": "string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "place": {
        "value": "verbatim-string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "term": {
        "value": "verbatim-string",
        "semantic_type": [
            "contract_end_date",
            "validity_period",
            "performance_deadline",
            "return_deadline",
            "indefinite",
            "other",
        ],
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "parties": [
        {
            "name": "verbatim-string",
            "role": "verbatim-string",
            "inn": "verbatim-string",
            "name_evidence": "verbatim-string",
            "name_page_number": "integer",
            "inn_evidence": "verbatim-string",
            "inn_page_number": "integer",
        }
    ],
    "total_amount": {
        "value": "number",
        "raw_value": "verbatim-string",
        "currency": "currency",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "vat": {
        "raw_value": "verbatim-string",
        "rate": "number",
        "mode": ["included", "excluded", "not_subject", "not_stated"],
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
}

INSTRUCTIONS = """
Извлеки реквизиты именно заключаемого договора из русскоязычного документа.

Правила:
1. Ничего не выдумывай. Если значение явно не найдено, верни null или пустой список.
2. contract_number — номер основного договора, а не номер приложения, счета, спецификации,
   доверенности или входящего письма.
3. contract_date — дата заключения основного договора. Не используй даты приложений,
   платежей, доверенностей или регистрации, если они не являются датой договора.
4. contract_type — вид заключаемого договора, например договор поставки, займа,
   подряда, хранения или оказания услуг. Подтверди его заголовком или предметом договора.
5. place — место заключения договора из шапки. Не используй адрес стороны, банка,
   суда, объекта работ или место исполнения обязательств.
6. term — срок действия договора или срок исполнения основного обязательства,
   соответствующий смыслу договора. Не используй срок оплаты, гарантии, уведомления
   или ответа на претензию. Если договор бессрочный, верни значение из документа
   и semantic_type=indefinite.
7. parties — стороны, которые заключают договор. Не считай сторонами банки, получателей
   платежа, контактных лиц и подписантов самих по себе. Роль бери из формулировок документа,
   например Заказчик, Исполнитель, Поставщик, Покупатель. Для названия и ИНН верни
   отдельные evidence и page_number. Не связывай ИНН одной стороны с другой стороной.
8. total_amount — общая цена/стоимость договора. Не подставляй отдельный платеж,
   штраф, обеспечение или сумму одной спецификации, если это не вся цена договора.
9. vat — режим и ставка НДС именно для общей суммы договора. Для формулировки
   "без НДС" используй mode=not_subject и rate=null. Если НДС не указан,
   используй mode=not_stated.
10. evidence должно быть короткой дословной цитатой, подтверждающей конкретное значение.
11. page_number должен соответствовать метке PAGE N, расположенной перед изображением страницы.
12. Для total_amount.value верни число без пробелов и обозначения валюты,
    а в total_amount.raw_value сохрани сумму дословно из документа.
""".strip()


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


def validate_extraction(
    result: dict[str, Any],
    document: DocumentIR,
) -> dict[str, Any]:
    """Исправляет только значения, однозначно проверяемые по evidence."""
    page_texts = {
        page.number or index + 1: _normalize_text(
            "\n".join(block.text for block in page.blocks)
        )
        for index, page in enumerate(document.pages)
    }

    evidence_fields = [
        ("contract_number", "evidence", "page_number"),
        ("contract_date", "evidence", "page_number"),
        ("contract_type", "evidence", "page_number"),
        ("place", "evidence", "page_number"),
        ("term", "evidence", "page_number"),
        ("total_amount", "evidence", "page_number"),
        ("vat", "evidence", "page_number"),
    ]
    for field_name, evidence_name, page_name in evidence_fields:
        item = result.get(field_name)
        if isinstance(item, dict):
            _repair_page_number(item, evidence_name, page_name, page_texts)

    parties = result.get("parties")
    if isinstance(parties, list):
        for party in parties:
            if not isinstance(party, dict):
                continue
            _repair_page_number(
                party,
                "name_evidence",
                "name_page_number",
                page_texts,
            )
            _repair_page_number(
                party,
                "inn_evidence",
                "inn_page_number",
                page_texts,
            )

    contract_date = result.get("contract_date")
    if isinstance(contract_date, dict):
        normalized_date = _date_from_evidence(contract_date.get("evidence"))
        if normalized_date is not None:
            contract_date["value"] = normalized_date

    return result


def _repair_page_number(
    item: dict[str, Any],
    evidence_name: str,
    page_name: str,
    page_texts: dict[int, str],
) -> None:
    evidence = item.get(evidence_name)
    if not isinstance(evidence, str) or not evidence.strip():
        return

    needle = _normalize_text(evidence)
    matching_pages = [
        page_number
        for page_number, page_text in page_texts.items()
        if needle in page_text
    ]
    if len(matching_pages) == 1:
        item[page_name] = matching_pages[0]


def _date_from_evidence(evidence: Any) -> str | None:
    if not isinstance(evidence, str):
        return None

    matches = re.findall(
        r"(?<!\d)([0-3]?\d)[./-]([01]?\d)[./-]((?:19|20)\d{2})(?!\d)",
        evidence,
    )
    valid_dates: list[date] = []
    for day, month, year in matches:
        try:
            valid_dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if len(valid_dates) == 1:
        return valid_dates[0].isoformat()
    return None


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


@lru_cache(maxsize=1)
def load_model() -> tuple[Any, Any]:
    """Загружает модель один раз на процесс и возвращает processor и model."""
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForMultimodalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    ).eval()
    return processor, model


def extract_contract_key_data(
    document: str | Path | DocumentIR,
    *,
    ocr_backend: OCRBackend | None = None,
    ocr_dpi: int = 200,
    start_page: int = 1,
    max_pages: int | None = None,
    thinking: bool = False,
    max_new_tokens: int = 2048,
) -> dict[str, Any]:
    """Извлекает реквизиты из PDF/DOCX или готового DocumentIR.

    PDF сначала проходит разбор цифрового слоя. Tesseract вызывается только для
    страниц без достаточного текста, после чего NuExtract3 получает единый текст.
    """
    if ocr_dpi <= 0:
        raise ValueError("ocr_dpi должен быть положительным")
    if start_page < 1:
        raise ValueError("start_page должен быть не меньше 1")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages должен быть не меньше 1")
    if max_new_tokens < 1:
        raise ValueError("max_new_tokens должен быть не меньше 1")

    if isinstance(document, DocumentIR):
        document_ir = document
    else:
        backend = ocr_backend or TesseractOCRBackend()
        document_ir = parse_document(
            document,
            ocr_backend=backend,
            ocr_dpi=ocr_dpi,
        )

    text = document_ir_to_text(
        document_ir,
        start_page=start_page,
        max_pages=max_pages,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA недоступна. Локальная модель требует GPU.")

    processor, model = load_model()
    messages = build_messages(text)
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        template=json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False, indent=2),
        instructions=INSTRUCTIONS,
        enable_thinking=thinking,
    ).to(model.device)

    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    generated_ids = generated_ids[:, inputs["input_ids"].shape[1] :]
    raw = processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()

    try:
        parsed = parse_json_output(raw)
    except Exception as exc:
        raise ValueError(f"Модель вернула невалидный JSON: {raw}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Модель вернула JSON, но не объект")
    return validate_extraction(parsed, document_ir)
