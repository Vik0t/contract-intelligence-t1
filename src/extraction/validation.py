"""Validate output types and evidence before model data reaches the database."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from src.extraction.context import evidence_pages
from src.extraction.schema import CONTRACT_TYPE_LABELS, TERM_SEMANTIC_TYPES


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
    if result["term"]["semantic_type"] not in TERM_SEMANTIC_TYPES:
        result["term"]["semantic_type"] = None
    if result["vat"]["mode"] not in {"included", "excluded", "not_subject", "not_stated"}:
        result["vat"]["mode"] = None
    return result


def merge_extractions(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer fields from the main agreement; later chunks fill only missing fields."""
    merged = deepcopy(results[0])
    for result in results[1:]:
        for key, item in result.items():
            if key == "parties":
                for party in item:
                    existing = next((current for current in merged[key] if
                                     (party.get("inn") and current.get("inn") == party["inn"]) or
                                     (party.get("name") and current.get("name") == party["name"])), None)
                    if existing is None:
                        merged[key].append(deepcopy(party))
                    else:
                        for name, value in party.items():
                            if existing.get(name) is None:
                                existing[name] = value
            elif key == "vat":
                current = merged[key]
                if current.get("rate") is None and current.get("mode") not in {"included", "excluded", "not_subject"} and not current.get("raw_value"):
                    merged[key] = deepcopy(item)
            elif merged[key].get("value") is None and not merged[key].get("raw_value"):
                merged[key] = deepcopy(item)
    return merged
