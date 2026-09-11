from __future__ import annotations

from datetime import date
from functools import lru_cache
import importlib.util
import logging
import json
import os
from pathlib import Path
import re
import platform
from typing import Any

from dotenv import load_dotenv
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor, BitsAndBytesConfig

from src.document_ir import DocumentIR
from src.ocr import OCRBackend, TesseractOCRBackend
from src.parsing import document_ir_to_text, parse_document

MODEL_ID = "numind/NuExtract3"
MODEL_QUANTIZATION_ENV = "CONTRACT_MODEL_QUANTIZATION"
DEFAULT_MODEL_QUANTIZATION = "bf16"

load_dotenv()
logger = logging.getLogger(__name__)

CONTRACT_TYPE_LABELS = [
    "Договор займа",
    "Договор перевозки",
    "Договор поставки",
    "Договор купли-продажи",
    "Договор возмездного оказания услуг",
    "Договор подряда",
    "Договор страхования имущества",
    "Договор хранения",
    "Договор коммерческой концессии",
    "Договор возмездного оказания образовательных услуг",
    "Договор страхования гражданской ответственности",
    "Трудовой договор",
    "Договор транспортно-экспедиционного обслуживания",
    "Договор оказания образовательных услуг",
]

TERM_SEMANTIC_TYPES = [
    "contract_end_date",
    "loan_repayment_date",
    "service_period_end_date",
]

IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

if IS_MACOS:
    # Do not import mlx-lm during module import: initializing MLX requires a
    # working Metal device and would otherwise abort test/API startup on hosts
    # where inference is not being used.
    MLX_AVAILABLE = importlib.util.find_spec("mlx_lm") is not None
else:
    MLX_AVAILABLE = False

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


 # The first prompt above is kept for backwards compatibility with old callers.
 # The active schema is intentionally stricter for contract type and term.
CONTRACT_TEMPLATE = {
     "contract_number": {
         "value": "verbatim-string-or-null",
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "contract_date": {
         "value": "YYYY-MM-DD-or-null",
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "contract_type": {
         "value": CONTRACT_TYPE_LABELS,
         "raw_value": "verbatim-string-or-null",
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "place": {
         "value": "verbatim-string-or-null",
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "term": {
         "value": "YYYY-MM-DD-or-null",
         "raw_value": "verbatim-string-or-null",
         "semantic_type": TERM_SEMANTIC_TYPES,
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "parties": [
         {
             "name": "verbatim-string-or-null",
             "role": "verbatim-string-or-null",
             "inn": "verbatim-string-or-null",
             "name_evidence": "verbatim-string-or-null",
             "name_page_number": "integer-or-null",
             "inn_evidence": "verbatim-string-or-null",
             "inn_page_number": "integer-or-null",
         }
     ],
     "total_amount": {
         "value": "number-or-null",
         "raw_value": "verbatim-string-or-null",
         "currency": "currency-or-null",
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
     "vat": {
         "raw_value": "verbatim-string-or-null",
         "rate": "number-or-null",
         "mode": ["included", "excluded", "not_subject", "not_stated"],
         "evidence": "verbatim-string-or-null",
         "page_number": "integer-or-null",
     },
 }

INSTRUCTIONS = f"""
Извлеки реквизиты именно заключаемого договора из русскоязычного документа.

Общие правила:
1. Ничего не выдумывай. Если значение явно не найдено, верни null или пустой список.
2. Для каждого значения верни короткое дословное evidence из документа.
3. Не путай основной договор с приложениями, счетами, доверенностями и письмами.

contract_type:
- value должен быть ровно одним значением из этого списка:
  {", ".join(CONTRACT_TYPE_LABELS)}.
- Определяй тип по заголовку и предмету договора, а не по случайным упоминаниям в реквизитах.
- Нормализуй формулировки: "перевозки" -> "Договор перевозки"; транспортная экспедиция ->
  "Договор транспортно-экспедиционного обслуживания".
- Для страхования различай имущество и гражданскую ответственность по предмету договора.
- Для образовательных услуг различай обычное оказание образовательных услуг и возмездное оказание.
- Не возвращай номер договора, скобки, пояснения или новый класс вне списка.

term:
- value возвращай только в формате YYYY-MM-DD.
- semantic_type выбирай только из:
  contract_end_date, loan_repayment_date, service_period_end_date.
- Выбирай дату окончания срока договора/займа/периода услуг, а не дату подписания.
- Если написано "с X по Y", возвращай дату Y.
- Для займа выбирай дату возврата или погашения займа.
- Игнорируй даты оплаты, платежей, поставки, гарантии, уведомлений, претензий и штрафов.
- raw_value и evidence должны содержать исходную формулировку срока.

contract_date:
- value также возвращай в формате YYYY-MM-DD.
- Не используй даты приложений, оплат, платежей и регистрации.
""".strip()


class ExtractionStats:
    """Token usage statistics for extraction operations."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def add_usage(self, prompt_tokens: int, completion_tokens: int):
        """Add token usage from a single extraction."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens

    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens
        }


# Global stats collector
_stats_collector = ExtractionStats()


def get_extraction_stats() -> dict:
    """Get current extraction statistics."""
    return _stats_collector.to_dict()


def reset_extraction_stats():
    """Reset extraction statistics."""
    global _stats_collector
    _stats_collector = ExtractionStats()


def _count_tokens_mlx(tokenizer, text: str) -> int:
    """Count tokens for MLX models."""
    try:
        return len(tokenizer.encode(text))
    except:
        # Fallback to approximate counting
        return len(text.split())


def _count_tokens_transformers(tokenizer_or_processor, text: str) -> int:
    """Count tokens for transformer models."""
    try:
        if hasattr(tokenizer_or_processor, 'tokenizer'):
            # It's a processor
            return len(tokenizer_or_processor.tokenizer.encode(text))
        else:
            # It's a tokenizer
            return len(tokenizer_or_processor.encode(text))
    except:
        # Fallback to approximate counting
        return len(text.split())


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


_RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_ISO_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})[-./]"
    r"(?P<month>\d{1,2})[-./](?P<day>\d{1,2})(?!\d)"
)
_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[./-](?P<month>\d{1,2})"
    r"[./-](?P<year>(?:19|20)\d{2})(?!\d)"
)
_WORD_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*[\"«»]?\s*"
    r"(?P<month>января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"(?P<year>(?:19|20)\d{2})(?!\d)"
)


def _date_from_parts(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_date_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for pattern, order in (
        (_ISO_DATE_RE, ("year", "month", "day")),
        (_NUMERIC_DATE_RE, ("day", "month", "year")),
    ):
        for match in pattern.finditer(text):
            values = {name: int(match.group(name)) for name in order}
            iso_value = _date_from_parts(
                values["day"],
                values["month"],
                values["year"],
            )
            if iso_value is not None:
                candidates.append(
                    {
                        "value": iso_value,
                        "start": match.start(),
                        "end": match.end(),
                        "raw": match.group(0),
                    }
                )

    for match in _WORD_DATE_RE.finditer(text):
        iso_value = _date_from_parts(
            int(match.group("day")),
            _RUSSIAN_MONTHS[match.group("month")],
            int(match.group("year")),
        )
        if iso_value is not None:
            candidates.append(
                {
                    "value": iso_value,
                    "start": match.start(),
                    "end": match.end(),
                    "raw": match.group(0),
                }
            )

    unique: dict[tuple[int, str], dict[str, Any]] = {}
    for candidate in candidates:
        prefix = text[max(0, candidate["start"] - 40) : candidate["start"]]
        candidate["after_to"] = bool(
            re.search(r"\bпо\s*[\"«»]?\s*$", prefix.casefold())
        )
        unique[(candidate["start"], candidate["value"])] = candidate
    return sorted(unique.values(), key=lambda item: item["start"])


def _date_from_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidates = _extract_date_candidates(value)
    if len(candidates) == 1:
        return candidates[0]["value"]
    return None


def _canonical_contract_type(text: str) -> str | None:
    normalized = _normalize_text(text).replace("ё", "е")
    if "транспортно-экспед" in normalized or "транспортнo-экспед" in normalized:
        return "Договор транспортно-экспедиционного обслуживания"
    if "коммерческ" in normalized and "концесс" in normalized:
        return "Договор коммерческой концессии"
    if "гражданск" in normalized and "ответствен" in normalized and "страх" in normalized:
        return "Договор страхования гражданской ответственности"
    if "образователь" in normalized:
        if "возмездн" in normalized:
            return "Договор возмездного оказания образовательных услуг"
        return "Договор оказания образовательных услуг"
    if "трудов" in normalized:
        return "Трудовой договор"
    if "страхован" in normalized:
        return "Договор страхования имущества"
    if "перевоз" in normalized:
        return "Договор перевозки"
    if "поставк" in normalized:
        return "Договор поставки"
    if "купл" in normalized or "продаж" in normalized:
        return "Договор купли-продажи"
    if "подряд" in normalized:
        return "Договор подряда"
    if "хранен" in normalized:
        return "Договор хранения"
    if "займ" in normalized or "заем" in normalized:
        return "Договор займа"
    if "услуг" in normalized or "оказан" in normalized:
        return "Договор возмездного оказания услуг"
    return None


def _normalize_contract_type(result: dict[str, Any], text: str) -> None:
    item = result.get("contract_type")
    if not isinstance(item, dict):
        return

    context = " ".join(
        str(value)
        for value in (
            item.get("value"),
            item.get("evidence"),
            text[:6000],
        )
        if value
    )
    canonical = _canonical_contract_type(context)
    if canonical is None:
        return
    if item.get("value") != canonical:
        if item.get("value"):
            item.setdefault("raw_value", item["value"])
        item["value"] = canonical


def _term_context(text: str, candidate: dict[str, Any]) -> str:
    sentence_start = max(
        text.rfind(".", 0, candidate["start"]),
        text.rfind(";", 0, candidate["start"]),
        text.rfind("\n", 0, candidate["start"]),
    )
    sentence_end_candidates = [
        position
        for position in (
            text.find(".", candidate["end"]),
            text.find(";", candidate["end"]),
            text.find("\n", candidate["end"]),
        )
        if position != -1
    ]
    sentence_end = min(sentence_end_candidates, default=len(text))
    start = sentence_start + 1
    end = sentence_end
    if end - start < 30:
        start = max(0, candidate["start"] - 100)
        end = min(len(text), candidate["end"] + 120)
    return _normalize_text(text[start:end]).replace("ё", "е")


def _term_semantic_type(context: str) -> str:
    if (
        ("займ" in context or "заем" in context)
        and any(word in context for word in ("возврат", "вернуть", "погаш"))
    ):
        return "loan_repayment_date"
    if "услуг" in context and any(word in context for word in ("период", "оказан", "срок")):
        return "service_period_end_date"
    return "contract_end_date"


def _term_candidate_score(
    candidate: dict[str, Any],
    context: str,
    predicted_dates: set[str],
    predicted_semantic_type: str | None,
) -> int:
    score = 0
    strong_cues = {
        "действует до": 12,
        "срок действия": 10,
        "срок договора": 10,
        "срок возврата": 12,
        "возврат": 9,
        "погаш": 9,
        "период оказания": 12,
        "оказания услуг": 7,
    }
    for cue, weight in strong_cues.items():
        if cue in context:
            score += weight
    if " до " in f" {context} ":
        score += 2
    if " по " in f" {context} ":
        score += 2
    if candidate.get("after_to"):
        score += 8
    for excluded in ("оплат", "платеж", "гарант", "уведом", "претенз", "штраф"):
        if excluded in context:
            score -= 8
    if "поставк" in context and "срок договора" not in context:
        score -= 4
    if candidate["value"] in predicted_dates:
        score += 6
    if predicted_semantic_type == _term_semantic_type(context):
        score += 3
    return score


def _evidence_snippet(text: str, candidate: dict[str, Any]) -> str:
    start = max(0, candidate["start"] - 100)
    end = min(len(text), candidate["end"] + 120)
    snippet = " ".join(text[start:end].split())
    return snippet[:320]


def _normalize_term(result: dict[str, Any], text: str) -> None:
    item = result.get("term")
    if not isinstance(item, dict):
        return

    candidates = _extract_date_candidates(text)
    if not candidates:
        normalized_value = _date_from_text(item.get("value")) or _date_from_text(item.get("evidence"))
        if normalized_value is not None:
            item["value"] = normalized_value
        return

    predicted_text = " ".join(
        str(value)
        for value in (item.get("value"), item.get("raw_value"), item.get("evidence"))
        if value
    )
    predicted_dates = {candidate["value"] for candidate in _extract_date_candidates(predicted_text)}
    predicted_semantic_type = item.get("semantic_type")
    scored_candidates = [
        (
            _term_candidate_score(
                candidate,
                _term_context(text, candidate),
                predicted_dates,
                predicted_semantic_type,
            ),
            candidate,
        )
        for candidate in candidates
    ]
    score, selected = max(scored_candidates, key=lambda pair: (pair[0], pair[1]["start"]))
    if score <= 0 and predicted_dates:
        selected = next(
            (candidate for candidate in candidates if candidate["value"] in predicted_dates),
            selected,
        )

    raw_value = item.get("raw_value") or item.get("value") or selected["raw"]
    item["raw_value"] = raw_value
    item["value"] = selected["value"]
    item["semantic_type"] = _term_semantic_type(_term_context(text, selected))
    existing_evidence = item.get("evidence")
    if not isinstance(existing_evidence, str) or selected["value"] not in {
        candidate["value"] for candidate in _extract_date_candidates(existing_evidence)
    }:
        item["evidence"] = _evidence_snippet(text, selected)


def postprocess_extraction(result: dict[str, Any], text: str) -> dict[str, Any]:
    """Canonicalize the two fields that need domain-aware selection."""
    _normalize_contract_type(result, text)
    _normalize_term(result, text)
    contract_date = result.get("contract_date")
    if isinstance(contract_date, dict):
        normalized_date = _date_from_text(contract_date.get("value"))
        if normalized_date is not None:
            contract_date["value"] = normalized_date
    return result


@lru_cache(maxsize=1)
def load_model() -> tuple[Any, Any]:
    """Загружает модель один раз на процесс."""
    if IS_MACOS and MLX_AVAILABLE:
        from mlx_lm import load as mlx_load

        model, tokenizer = mlx_load("numind/NuExtract3-mlx-8bits")
        return model, tokenizer
    
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available() and not IS_MACOS:
        device = "mps"
    else:
        device = "cpu"

    requested_mode = os.getenv(MODEL_QUANTIZATION_ENV, DEFAULT_MODEL_QUANTIZATION).strip().lower()
    if requested_mode not in {"bf16", "8bit"}:
        raise ValueError(
            f"{MODEL_QUANTIZATION_ENV} must be 'bf16' or '8bit', got {requested_mode!r}"
        )

    if device == "cuda" and requested_mode == "bf16" and torch.cuda.is_bf16_supported():
        effective_mode = "bf16"
        dtype = torch.bfloat16
    elif device == "cuda":
        effective_mode = "8bit"
        dtype = torch.float16
        if requested_mode == "bf16":
            logger.warning("BF16 is unavailable on this CUDA device; falling back to 8-bit.")
    else:
        effective_mode = "full"
        dtype = torch.float32
        if requested_mode == "8bit":
            logger.warning("8-bit quantization is only enabled for CUDA; using full precision on %s.", device)

    model_kwargs = {
        "dtype": dtype,
        "device_map": device,
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
    }
    if effective_mode == "8bit":
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_threshold=6.0,
        )

    logger.info(
        "Loading %s with mode=%s, device=%s, dtype=%s",
        MODEL_ID,
        effective_mode,
        device,
        dtype,
    )
    try:
        model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, **model_kwargs).eval()
    except (RuntimeError, TypeError, ValueError, OSError):
        if effective_mode != "bf16" or device != "cuda":
            raise
        logger.exception("BF16 model loading failed; retrying with 8-bit CUDA quantization.")
        torch.cuda.empty_cache()
        fallback_kwargs = {
            "dtype": torch.float16,
            "device_map": device,
            "quantization_config": BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
            ),
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, **fallback_kwargs).eval()
    return processor, model


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

    if IS_MACOS and MLX_AVAILABLE:
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

        # Count prompt tokens
        prompt_tokens = _count_tokens_mlx(tokenizer, prompt)

        raw = mlx_generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_new_tokens
        )

        # Count completion tokens
        completion_tokens = _count_tokens_mlx(tokenizer, raw)

        raw = raw.strip()

        try:
            parsed = parse_json_output(raw)
        except Exception as exc:
            raise ValueError(f"Модель вернула невалидный JSON: {raw}") from exc
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

        # Count prompt tokens
        prompt_tokens = inputs["input_ids"].shape[1]

        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated_ids = generated_ids[:, inputs["input_ids"].shape[1]:]

        # Count completion tokens
        completion_tokens = generated_ids.shape[1]

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

        parsed = postprocess_extraction(parsed, text)

        if document_ir is not None:
            parsed = validate_extraction(parsed, document_ir)

    # Record stats if requested
    if collect_stats:
        _stats_collector.add_usage(prompt_tokens, completion_tokens)

    return parsed


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

    if document is not None:
        extracted_text, extracted_document_ir = extract_text_from_document(
            document,
            ocr_backend=ocr_backend,
            ocr_dpi=ocr_dpi,
            start_page=start_page,
            max_pages=max_pages,
        )
        result = extract_fields_from_text(
            extracted_text,
            extracted_document_ir,
            thinking=thinking,
            max_new_tokens=max_new_tokens,
            collect_stats=collect_stats,
        )
    else:
        result = extract_fields_from_text(
            text,
            document_ir,
            thinking=thinking,
            max_new_tokens=max_new_tokens,
            collect_stats=collect_stats,
        )

    if collect_stats:
        return result, _stats_collector.to_dict()
    return result, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
