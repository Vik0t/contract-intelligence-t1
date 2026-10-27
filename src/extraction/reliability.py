"""Field statuses, consistency checks and source locations required by the PMI."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

RULES_VERSION = "2026-10-27.1"
CORE_FIELDS = ("contract_number", "contract_date", "parties", "total_amount")
ROLE_MAPPING = {
    "заказчик": "Заказчик", "покупатель": "Заказчик", "арендатор": "Заказчик",
    "заёмщик": "Заказчик", "заемщик": "Заказчик", "поклажедатель": "Заказчик",
    "исполнитель": "Исполнитель", "поставщик": "Исполнитель", "подрядчик": "Исполнитель",
    "арендодатель": "Исполнитель", "займодавец": "Исполнитель", "хранитель": "Исполнитель",
}


def normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def canonical_role(role: str | None) -> str | None:
    return ROLE_MAPPING.get(normalized(role).strip(' «»".,:'))


def total_candidates(text: str) -> list[dict[str, Any]]:
    """Only explicit contract totals; advances, VAT and unit prices are not totals."""
    pattern = re.compile(
        r"(?:общая\s+(?:сумма|стоимость)(?:\s+(?:настоящего\s+)?договора)?|(?:сумма|цена|стоимость)\s+(?:настоящего\s+)?договора)"
        r"\s*(?:(?:составля[ею]т|равна|в размере)\s*|[:=|]\s*|[-–—]\s+)?"
        r"(?P<amount>-?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?)",
        re.I,
    )
    candidates = []
    for match in pattern.finditer(text):
        try:
            value = float(Decimal(re.sub(r"\s", "", match['amount']).replace(",", ".")))
        except InvalidOperation:
            continue
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        evidence = text[start:end if end != -1 else len(text)].strip()
        pages = re.findall(r"(?m)^PAGE (\d+)\s*$", text[:match.start()])
        candidate = {"value": value, "evidence": evidence, "page_number": int(pages[-1]) if pages else None}
        if not any(c["value"] == value and c["evidence"] == evidence for c in candidates):
            candidates.append(candidate)
    return candidates


def assess_fields(result: dict[str, Any], text: str = "", *, document=None,
                  reference_date: date | datetime | None = None, method: str | None = None) -> dict[str, Any]:
    """Preserve questionable candidates, but never label them as found."""
    cutoff = reference_date.date() if isinstance(reference_date, datetime) else reference_date or date.today()
    quality = {}
    for key in CORE_FIELDS:
        result.setdefault(key, [] if key == 'parties' else {'value': None, 'evidence': None})

    def location(item, evidence_key="evidence"):
        evidence = item.get(evidence_key)
        if document and evidence:
            matches = [(page.number, index + 1) for page in document.pages
                       for index, block in enumerate(page.blocks)
                       if normalized(evidence) in normalized(block.text)]
            if len(matches) == 1:
                if str(document.source_format) == "docx":
                    item["paragraph_number"] = matches[0][1]
                else:
                    item["page_number" if evidence_key == "evidence" else "name_page_number"] = matches[0][0]
            elif str(document.source_format) == 'docx':
                blocks = [normalized(block.text) for page in document.pages for block in page.blocks]
                joined = ' '.join(blocks)
                needle = normalized(evidence)
                offset = joined.find(needle)
                if offset >= 0 and joined.find(needle, offset + 1) < 0:
                    end = 0
                    for index, block in enumerate(blocks):
                        end += len(block) + 1
                        if offset < end:
                            item['paragraph_number'] = index + 1
                            break
        item["method"] = method or item.get('method') or 'LLM'

    for key, item in result.items():
        if key.startswith("_") or key == "parties" or not isinstance(item, dict):
            continue
        location(item)
        value = item.get("value") if "value" in item else item.get("raw_value") or item.get("mode")
        reason = item.get("reason") if item.get("status") == "needs_review" else None
        if key == "contract_date" and value:
            try:
                if date.fromisoformat(value) > cutoff:
                    reason = "Дата договора позже даты загрузки"
            except (ValueError, TypeError):
                reason = "Некорректная календарная дата"
        if key == "total_amount" and isinstance(value, (int, float)) and value <= 0:
            reason = "Сумма договора должна быть положительной"
        if key in {"contract_number", "contract_date"} and re.match(
            r"\s*(?:приложени|сч[её]т|доверенност)", item.get("evidence") or "", re.I
        ):
            reason = "Источник относится к приложению, счёту или доверенности"
        if key == "total_amount":
            evidence = item.get("evidence") or ""
            item.pop('amount_basis', None)
            if (value is not None and re.search(r'оклад|заработн\w*\s+плат', evidence, re.I)
                    and re.search(r'в\s+месяц|ежемесячн', evidence, re.I)
                    and not re.search(r'(?:сумма|стоимость|цена)\s+(?:настоящего\s+)?договора', evidence, re.I)):
                item['amount_basis'] = 'monthly_salary'
                reason = 'В источнике указан месячный оклад; общая сумма договора не подтверждена'
            if re.search(r"аванс|штраф|неустойк|цен[аы]\s+(?:за\s+)?единиц", evidence, re.I) and not total_candidates(evidence):
                reason = "Источник не подтверждает общую сумму договора"
            currency = item.get("currency")
            currency_patterns = {"RUB": r"RUB|руб|₽", "USD": r"USD|доллар|\$", "EUR": r"EUR|евро|€",
                                 "CNY": r"CNY|юан|¥", "KZT": r"KZT|тенге|₸", "GBP": r"GBP|фунт|£"}
            if currency and not re.search(currency_patterns.get(currency, re.escape(currency)), evidence, re.I):
                item["currency"] = None
            candidates = total_candidates(text)
            if len({candidate["value"] for candidate in candidates}) > 1:
                item["candidates"] = candidates
                reason = "Найдены несколько различных общих сумм договора"
        if item.get("candidates") and len({str(c.get("value")) for c in item["candidates"]}) > 1:
            reason = reason or "Найдены несколько различных значений"
        status = "needs_review" if reason else "not_found" if value is None or value == "" else "found" if item.get("evidence") else "needs_review"
        item.update(status=status, reason=reason or ("Нет фрагмента-источника" if status == "needs_review" else None))
        quality[key] = {name: item.get(name) for name in ("status", "reason", "method", "paragraph_number", "page_number", "evidence", "candidates")}
        for candidate in item.get('candidates', []):
            location(candidate)

    parties = result.get("parties", [])
    if not isinstance(parties, list):
        parties = []
    result['parties'] = parties
    reason = None
    names = [normalized(party.get("name")).translate(str.maketrans('', '', '«»"')) for party in parties]
    inns = [party.get("inn") for party in parties if party.get("inn")]
    if len(parties) < 2:
        reason = "Не найдены две стороны договора"
    elif len(set(names)) < len(names) or len(set(inns)) < len(inns):
        reason = "Стороны договора должны быть различными"
    for party in parties:
        location(party, "name_evidence")
        party["canonical_role"] = canonical_role(party.get("role"))
        party_reason = reason or party.get('grounding_reason') or ("Не определено название или роль стороны" if not party.get("name") or not party["canonical_role"] else None)
        party.update(status="needs_review" if party_reason or not party.get("name_evidence") else "found",
                     reason=party_reason or ("Нет фрагмента-источника" if not party.get("name_evidence") else None))
    if not reason and {p.get("canonical_role") for p in parties} != {"Заказчик", "Исполнитель"}:
        reason = "Не удалось однозначно сопоставить роли Заказчика и Исполнителя"
    reason = reason or next((p.get('reason') for p in parties if p.get('reason')), None)
    quality["parties"] = {"status": "not_found" if not parties else "needs_review" if reason or any(p["status"] != "found" for p in parties) else "found",
                          "reason": reason, "method": method or next((p['method'] for p in parties), 'LLM')}
    result["_quality"] = quality
    return result
