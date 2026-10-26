"""Dataset scoring independent of model inference and test-framework imports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import product
import re
import statistics
import unicodedata

FIELDS = ("contract_number", "contract_date", "contract_type", "place", "term",
          "party1_name", "party2_name", "party1_inn", "party2_inn", "total_amount", "vat")
MISSING = {"", "не указано", "не указан", "не указана", "not specified", "not found", "нет"}


def norm(value) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value if value is not None else "")).casefold().replace("ё", "е").replace("\u00ad", "-").split())


def missing(value) -> bool:
    return value is None or norm(value) in MISSING


def name(value) -> str:
    text = norm(value)
    for source, target in (("общество с ограниченной ответственностью", "ооо"),
                           ("публичное акционерное общество", "пао"),
                           ("закрытое акционерное общество", "зао"),
                           ("открытое акционерное общество", "оао"),
                           ("акционерное общество", "ао"), ("индивидуальный предприниматель", "ип")):
        text = text.replace(source, target)
    text = re.sub(r"[«»\"'“”]", "", text)
    text = re.sub(r"^граждан(?:ин|ка)\s+(?:рф\s+)?", "", text)
    return " ".join(text.split())


def number(value) -> str:
    raw = re.sub(r"^\s*№\s*", "", str(value if value is not None else ""))
    return re.sub(r"\s+", "", norm(raw)).replace("–", "-").replace("—", "-")


def place(value) -> str:
    return re.sub(r"^(?:город\s+|г(?:\.\s*|\s+))", "", norm(value))


def iso_date(value) -> str | None:
    text = str(value or "")
    for pattern, order in ((r"(?<!\d)((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", "ymd"),
                           (r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})(?!\d)", "dmy")):
        match = re.search(pattern, text)
        if match:
            parts = dict(zip(order, map(int, match.groups())))
            try:
                return date(parts["y"], parts["m"], parts["d"]).isoformat()
            except ValueError:
                return None
    return None


def amount(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        result = Decimal(text)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def score_legacy(gold: dict, result: dict) -> dict[str, bool | None]:
    def value(key):
        return (result.get(key) or {}).get("value")

    scores = {
        "contract_number": number(value("contract_number")) == number(gold["number"]),
        "contract_date": iso_date(value("contract_date")) == iso_date(gold["date"]),
        "contract_type": norm(value("contract_type")) == norm(gold["contract_type"]),
        "place": place(value("place")) == place(gold["place"]),
        "term": iso_date(value("term")) == iso_date(gold["term"]),
        "total_amount": amount(value("total_amount")) == amount(gold["amount"]),
    }
    # Bad/unparseable gold dates must not produce a false success through None==None.
    for key, label in (("contract_date", "date"), ("term", "term")):
        if not missing(gold[label]) and iso_date(gold[label]) is None:
            scores[key] = None
    predicted = [item for item in result.get("parties", []) if isinstance(item, dict)]
    candidates = [-1, *range(len(predicted))]

    def party(index):
        return predicted[index] if index >= 0 else {}

    # Keep each INN attached to its company. Swapped INNs cannot pass by membership.
    def alignment_score(pair):
        return sum(10 * (name(party(index).get("name")) == name(gold[f"party{position}"]))
                   + (not missing(gold.get(f"inn{position}")) and norm(party(index).get("inn")) == norm(gold[f"inn{position}"]))
                   for position, index in enumerate(pair, start=1))

    assignments = [pair for pair in product(candidates, repeat=2) if pair[0] == -1 or pair[1] == -1 or pair[0] != pair[1]]
    selected = max(assignments, key=alignment_score)
    for position, index in enumerate(selected, start=1):
        item = party(index)
        scores[f"party{position}_name"] = name(item.get("name")) == name(gold[f"party{position}"])
        expected = gold.get(f"inn{position}")
        scores[f"party{position}_inn"] = missing(item.get("inn")) if missing(expected) else norm(item.get("inn")) == norm(expected)
    vat = result.get("vat") or {}
    vat_gold = norm(gold["vat"])
    percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%", vat_gold)
    if "без ндс" in vat_gold:
        scores["vat"] = vat.get("mode") == "not_subject"
    elif percent:
        scores["vat"] = amount(vat.get("rate")) == amount(percent.group(1))
    elif vat_gold == "0":
        # Legacy labels do not distinguish zero-rated from VAT-exempt contracts.
        scores["vat"] = amount(vat.get("rate")) == Decimal(0) or vat.get("mode") == "not_subject"
    else:
        scores["vat"] = None
    return {key: scores[key] for key in FIELDS}


def summarize(records: list[dict]) -> dict:
    labeled = [item for item in records if item.get("field_scores") is not None]
    field_totals = {key: {"correct": 0, "total": 0} for key in FIELDS}
    for item in labeled:
        for key, passed in item["field_scores"].items():
            if passed is not None:
                field_totals[key]["total"] += 1
                field_totals[key]["correct"] += bool(passed)
    correct = sum(item["correct"] for item in field_totals.values())
    total = sum(item["total"] for item in field_totals.values())
    for values in field_totals.values():
        values["accuracy"] = values["correct"] / values["total"] if values["total"] else None
    timings = sorted(item["extraction_sec"] for item in records if item.get("status") == "ok" and item.get("extraction_sec") is not None)
    completed_checks = [value for item in labeled if item.get("status") == "ok" for value in item["field_scores"].values() if value is not None]
    return {
        "files": len(records), "unique_contracts": len({item["document_id"] for item in records}),
        "labeled_files": len(labeled), "labeled_contracts": len({item["document_id"] for item in labeled}),
        "successful_files": sum(item.get("status") == "ok" for item in records),
        "failed_files": sum(item.get("status") != "ok" for item in records),
        "inference_calls": sum(item.get("inference_executed", True) for item in records),
        "identical_inputs_reused": sum(item.get("inference_executed") is False for item in records),
        "correct_fields": correct, "scored_fields": total, "field_accuracy": correct / total if total else None,
        "field_accuracy_on_successful_files": sum(completed_checks) / len(completed_checks) if completed_checks else None,
        "all_fields_correct_files": sum(all(value for value in item["field_scores"].values() if value is not None) for item in labeled),
        "per_field": field_totals,
        "median_extraction_sec": statistics.median(timings) if timings else None,
        "p95_extraction_sec": timings[min(len(timings) - 1, max(0, int(len(timings) * .95 + .999) - 1))] if timings else None,
        "insights_completed": sum(item.get("insights", {}).get("status") == "ok" for item in records),
        "insight_errors": sum(item.get("insights", {}).get("status") == "error" for item in records),
    }
