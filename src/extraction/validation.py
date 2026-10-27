"""Validate output types and evidence before model data reaches the database."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from src.extraction.context import evidence_pages
from src.extraction.schema import CONTRACT_TYPE_LABELS, TERM_SEMANTIC_TYPES
from src.extraction.reliability import assess_fields
from src.extraction.party_resolution import merge_parties, link_from_source, name_spans


class FieldValue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: StrictStr | None = None
    raw_value: StrictStr | None = None
    evidence: StrictStr | None = None
    page_number: StrictInt | None = None


class TermValue(FieldValue):
    semantic_type: StrictStr | None = None


class AmountValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    value: StrictFloat | StrictInt | None = None
    raw_value: StrictStr | None = None
    currency: StrictStr | None = None
    evidence: StrictStr | None = None
    page_number: StrictInt | None = None


class VatValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    raw_value: StrictStr | None = None
    rate: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=100)
    mode: StrictStr | None = None
    evidence: StrictStr | None = None
    page_number: StrictInt | None = None


class PartyValue(BaseModel):
    name: StrictStr | None = None
    role: StrictStr | None = None
    inn: StrictStr | None = None
    name_evidence: StrictStr | None = None
    name_page_number: StrictInt | None = None
    inn_evidence: StrictStr | None = None
    inn_page_number: StrictInt | None = None


class ContractResult(BaseModel):
    contract_number: FieldValue = Field(default_factory=FieldValue)
    contract_date: FieldValue = Field(default_factory=FieldValue)
    contract_type: FieldValue = Field(default_factory=FieldValue)
    place: FieldValue = Field(default_factory=FieldValue)
    term: TermValue = Field(default_factory=TermValue)
    parties: list[PartyValue] = Field(default_factory=list)
    total_amount: AmountValue = Field(default_factory=AmountValue)
    vat: VatValue = Field(default_factory=VatValue)


def validate_model_result(data: dict[str, Any], text: str) -> dict[str, Any]:
    if not any(key in data for key in ContractResult.model_fields):
        raise ValueError("Модель не вернула поля договора")
    data = {key: value for key, value in data.items() if value is not None}
    result = ContractResult.model_validate(data).model_dump()
    normalize = lambda value: " ".join(value.casefold().split())
    source = normalize(text)

    def ground(item, evidence_key, page_key, value_keys):
        evidence = item.get(evidence_key)
        if not evidence or normalize(evidence) not in source:
            for key in value_keys:
                item[key] = None
            item[evidence_key] = None
            item[page_key] = None
            return
        pages = evidence_pages(text, evidence)
        page = item.get(page_key)
        item[page_key] = page if page in pages else pages[0] if len(pages) == 1 else None

    for key, item in result.items():
        if key != "parties":
            ground(item, "evidence", "page_number", [name for name in item if name not in {"evidence", "page_number"}])
    for party in result["parties"]:
        ground(party, "name_evidence", "name_page_number", ["name", "role"])
        ground(party, "inn_evidence", "inn_page_number", ["inn"])
        if party.get('name') and not name_spans(party['name'], party.get('name_evidence') or ''):
            party['grounding_reason'] = 'Фрагмент не подтверждает наименование стороны'
    number = result['contract_number']
    if number.get('value') and normalize(number['value']).replace(' ', '') not in normalize(number.get('evidence') or '').replace(' ', ''):
        number.update(status='needs_review', reason='Фрагмент не подтверждает извлечённый номер')
    total = result['total_amount']
    if total.get('value') is not None:
        numbers = re.findall(r'(?<!\w)-?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?(?!\d)', total.get('evidence') or '')
        if Decimal(str(total['value'])) not in {Decimal(re.sub(r'\s', '', value).replace(',', '.')) for value in numbers}:
            total.update(status='needs_review', reason='Фрагмент не подтверждает извлечённую сумму')
    result["parties"] = [party for party in result["parties"] if party["name"] or party["inn"]]
    if result["contract_type"]["value"] not in CONTRACT_TYPE_LABELS:
        result["contract_type"]["value"] = None
    for key in ("contract_date", "term"):
        value = result[key]["value"]
        try:
            if value:
                date.fromisoformat(value)
        except ValueError:
            result[key]["value"] = None
            result[key].update(status="needs_review", reason="Некорректная календарная дата")
    from src.extraction.postprocess import _extract_date_candidates
    item = result['contract_date']
    if item.get('value') and item.get('evidence'):
        dates = {candidate['value'] for candidate in _extract_date_candidates(item['evidence'])}
        if item['value'] not in dates:
            item.update(status='needs_review', reason='Фрагмент не подтверждает дату договора')
    if result["term"]["semantic_type"] not in TERM_SEMANTIC_TYPES:
        result["term"]["semantic_type"] = None
    if result["vat"]["mode"] not in {"included", "excluded", "not_subject", "not_stated"}:
        result["vat"]["mode"] = None
    return assess_fields(result, text)


def merge_extractions(results: list[dict[str, Any]], text: str = "", document_ir=None) -> dict[str, Any]:
    """Keep sources from every chunk and expose conflicting candidates for review."""
    if not results:
        raise ValueError("Нет результатов извлечения")
    merged = deepcopy(results[0])
    for result in results[1:]:
        for key, item in result.items():
            if key.startswith("_"):
                continue
            if key == "parties":
                merged[key] = merge_parties(merged[key], item)
            elif key == "vat":
                current = merged[key]
                if current.get("rate") is None and current.get("mode") not in {"included", "excluded", "not_subject"} and not current.get("raw_value"):
                    merged[key] = deepcopy(item)
            elif merged[key].get("value") is None and not merged[key].get("raw_value"):
                merged[key] = deepcopy(item)
            elif key in {"contract_number", "contract_date", "total_amount"} and item.get("value") is not None:
                current = merged[key]
                if current.get("value") != item["value"] or (key == "total_amount" and current.get("currency") and item.get("currency") and current["currency"] != item["currency"]):
                    candidates = current.setdefault("candidates", [{k: current.get(k) for k in ("value", "currency", "evidence", "page_number")}])
                    candidate = {k: item.get(k) for k in ("value", "currency", "evidence", "page_number")}
                    if candidate not in candidates:
                        candidates.append(candidate)
                    current.update(status="needs_review", reason="Найдены несколько различных значений")
    merged['parties'], issues = link_from_source(merged.get('parties', []), text, document_ir)
    if text:
        from src.extraction.postprocess import postprocess_extraction, validate_extraction
        from src.extraction.header_fields import recover_header_fields
        merged = postprocess_extraction(merged, text)
        merged = recover_header_fields(merged, text)
        if document_ir is not None:
            merged = validate_extraction(merged, document_ir)
        for key in ('contract_type', 'term', 'vat'):
            item = merged.get(key) or {}
            pages = evidence_pages(text, item.get('evidence') or '')
            if item.get('page_number') not in pages:
                item['page_number'] = pages[0] if len(pages) == 1 else None
    merged = assess_fields(merged, text)
    if issues:
        merged['_quality']['parties'].update(status='needs_review', reason='; '.join(issues))
    return merged
