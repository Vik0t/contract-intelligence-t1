from __future__ import annotations

from datetime import date
import re
from typing import Any

from src.document_ir import DocumentIR


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
            _repair_page_number(party, "name_evidence", "name_page_number", page_texts)
            _repair_page_number(party, "inn_evidence", "inn_page_number", page_texts)

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
        page_number for page_number, page_text in page_texts.items() if needle in page_text
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
            iso_value = _date_from_parts(values["day"], values["month"], values["year"])
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
        candidate["after_to"] = bool(re.search(r"\bпо\s*[\"«»]?\s*$", prefix.casefold()))
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

    from src.extraction.schema import CONTRACT_TYPE_LABELS
    if item.get("value") in CONTRACT_TYPE_LABELS:
        return

    context = " ".join(
        str(value)
        for value in (item.get("value"), item.get("evidence"), text[:6000])
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
    if ("займ" in context or "заем" in context) and any(
        word in context for word in ("возврат", "вернуть", "погаш")
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
    predicted_dates = {c["value"] for c in _extract_date_candidates(predicted_text)}
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
    scored_candidates = [
        (score, candidate) for score, candidate in scored_candidates
        if _term_candidate_score(candidate, _term_context(text, candidate), set(), None) >= 7
    ]
    if not scored_candidates:
        item["value"] = None
        item["semantic_type"] = None
        item["evidence"] = None
        item["page_number"] = None
        return
    score, selected = max(scored_candidates, key=lambda pair: (pair[0], pair[1]["start"]))
    if score <= 0 and predicted_dates:
        selected = next(
            (c for c in candidates if c["value"] in predicted_dates),
            selected,
        )

    raw_value = item.get("raw_value") or item.get("value") or selected["raw"]
    item["raw_value"] = raw_value
    item["value"] = selected["value"]
    item["semantic_type"] = _term_semantic_type(_term_context(text, selected))
    existing_evidence = item.get("evidence")
    if not isinstance(existing_evidence, str) or selected["value"] not in {
        c["value"] for c in _extract_date_candidates(existing_evidence)
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
