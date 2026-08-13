from __future__ import annotations

import json
import os
import re
import statistics
from pathlib import Path
from typing import Any


RESULTS_PATH = Path(os.environ.get("RESULTS_PATH", "tmp/eval_50_results.json"))
METRICS_OUTPUT = Path(os.environ.get("METRICS_OUTPUT", "tmp/eval_50_metrics_new_meta.json"))
META_DIR = Path("meta")

FIELDS = [
    "contract_number",
    "contract_date",
    "contract_type",
    "place",
    "term",
    "party1_name",
    "party2_name",
    "party1_inn",
    "party2_inn",
    "total_amount",
    "vat",
]

MONTHS = {
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


def norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def is_missing(value: Any) -> bool:
    return value is None or norm(value) in {
        "",
        "not specified",
        "not found",
        "не указано",
        "не указан",
        "не указана",
    }


def date_value(value: Any) -> str | None:
    text = norm(value)
    match = re.search(r"([0-9]{4})[-./]([0-9]{1,2})[-./]([0-9]{1,2})", text)
    if match and match.group(1).startswith(("19", "20")):
        year, month, day = map(int, match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"

    match = re.search(r"([0-9]{1,2})[./-]([0-9]{1,2})[./-]([0-9]{4})", text)
    if match and match.group(3).startswith(("19", "20")):
        day, month, year = map(int, match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"

    match = re.search(
        r"([0-9]{1,2})\s+"
        r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)\s+([0-9]{4})",
        text,
    )
    if match and match.group(3).startswith(("19", "20")):
        day, month, year = match.groups()
        return f"{int(year):04d}-{MONTHS[month]:02d}-{int(day):02d}"
    return None


def canonical_name(value: Any) -> str:
    text = norm(value).replace("«", "").replace("»", "")
    text = text.replace('"', "").replace("'", "")
    for source, replacement in (
        ("публичное акционерное общество", "пао"),
        ("закрытое акционерное общество", "зао"),
        ("акционерное общество", "ао"),
        ("общество с ограниченной ответственностью", "ооо"),
        ("индивидуальный предприниматель", "ип"),
    ):
        text = text.replace(source, replacement)
    return " ".join(text.split())


def canonical_place(value: Any) -> str:
    text = norm(value).replace("«", "").replace("»", "")
    text = re.sub(r"^г\.?\s+", "", text)
    text = re.sub(r"^город\s+", "", text)
    return text


def number_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", text)
    return float(match.group()) if match else None


def scalar_equal(predicted: Any, gold: Any) -> bool:
    if is_missing(gold):
        return is_missing(predicted)
    return norm(predicted) == norm(gold)


def vat_mode_equal(predicted: Any, gold: Any) -> bool:
    expected = norm(gold)
    actual = norm(predicted)
    if expected == "not_applicable":
        return actual in {"not_subject", "not_applicable"}
    if expected in {"", "not_found"}:
        return actual in {"", "not_stated", "not_found"}
    return actual == expected


def vat_value_equal(predicted: Any, gold: Any) -> bool:
    expected = number_value(gold.get("normalized_value"))
    actual = number_value(predicted.get("rate")) if isinstance(predicted, dict) else None
    status = norm(gold.get("status"))
    mode = norm(gold.get("mode"))
    if status == "not_found":
        return actual is None
    if expected == 0 and mode in {"not_applicable", "included"}:
        raw = norm(predicted.get("raw_value")) if isinstance(predicted, dict) else ""
        evidence = norm(predicted.get("evidence")) if isinstance(predicted, dict) else ""
        non_taxable_text = any(
            marker in raw or marker in evidence
            for marker in ("без ндс", "не облага", "не начисля", "не выделя")
        )
        return actual in {None, 0} and (
            norm(predicted.get("mode")) in {"not_subject", "not_stated"}
            or non_taxable_text
        )
    return actual == expected


def evidence_page_ok(item: Any, predicted: Any) -> bool | None:
    if not isinstance(item, dict) or not item.get("evidence"):
        return None
    if not isinstance(predicted, dict):
        return False
    pages = {evidence.get("page") for evidence in item["evidence"]}
    return predicted.get("page_number") in pages


def score_document(gold: dict[str, Any], result: dict[str, Any]) -> tuple[dict[str, bool], dict[str, bool]]:
    def output_item(field: str) -> dict[str, Any]:
        value = result.get(field)
        return value if isinstance(value, dict) else {}

    scores: dict[str, bool] = {}
    pages: dict[str, bool] = {}

    contract_number = output_item("contract_number")
    gold_number = gold["contract_number"]
    scores["contract_number"] = scalar_equal(contract_number.get("value"), gold_number.get("normalized_value"))
    page_ok = evidence_page_ok(gold_number, contract_number)
    if page_ok is not None:
        pages["contract_number"] = page_ok

    contract_date = output_item("contract_date")
    scores["contract_date"] = date_value(contract_date.get("value")) == date_value(gold["contract_date"].get("normalized_value"))
    page_ok = evidence_page_ok(gold["contract_date"], contract_date)
    if page_ok is not None:
        pages["contract_date"] = page_ok

    contract_type = output_item("contract_type")
    scores["contract_type"] = scalar_equal(contract_type.get("value"), gold["contract_type"].get("normalized_value"))
    page_ok = evidence_page_ok(gold["contract_type"], contract_type)
    if page_ok is not None:
        pages["contract_type"] = page_ok

    place = output_item("place")
    scores["place"] = canonical_place(place.get("value")) == canonical_place(gold["place"].get("normalized_value"))
    page_ok = evidence_page_ok(gold["place"], place)
    if page_ok is not None:
        pages["place"] = page_ok

    term = output_item("term")
    scores["term"] = date_value(term.get("value")) == date_value(gold["term"].get("normalized_value"))
    page_ok = evidence_page_ok(gold["term"], term)
    if page_ok is not None:
        pages["term"] = page_ok

    predicted_parties = result.get("parties")
    predicted_parties = predicted_parties if isinstance(predicted_parties, list) else []
    gold_parties = sorted(gold["parties"], key=lambda item: item.get("order", 0))
    for index, gold_party in enumerate(gold_parties[:2], start=1):
        predicted_party = predicted_parties[index - 1] if index <= len(predicted_parties) and isinstance(predicted_parties[index - 1], dict) else {}
        gold_name = gold_party["name"]
        gold_inn = gold_party["inn"]
        name_field = f"party{index}_name"
        inn_field = f"party{index}_inn"
        scores[name_field] = canonical_name(predicted_party.get("name")) == canonical_name(gold_name.get("normalized_value"))
        scores[inn_field] = scalar_equal(predicted_party.get("inn"), gold_inn.get("normalized_value"))
        page_ok = evidence_page_ok(gold_name, predicted_party | {"page_number": predicted_party.get("name_page_number")})
        if page_ok is not None:
            pages[name_field] = page_ok
        page_ok = evidence_page_ok(gold_inn, predicted_party | {"page_number": predicted_party.get("inn_page_number")})
        if page_ok is not None:
            pages[inn_field] = page_ok

    amount = output_item("total_amount")
    scores["total_amount"] = number_value(amount.get("value")) == number_value(gold["total_amount"].get("normalized_value"))
    page_ok = evidence_page_ok(gold["total_amount"], amount)
    if page_ok is not None:
        pages["total_amount"] = page_ok

    vat = output_item("vat")
    gold_vat = gold["vat"]
    vat_value_ok = vat_value_equal(vat, gold_vat)
    vat_mode_ok = vat_mode_equal(vat.get("mode"), gold_vat.get("mode"))
    scores["vat"] = vat_value_ok and vat_mode_ok
    page_ok = evidence_page_ok(gold_vat, vat)
    if page_ok is not None:
        pages["vat"] = page_ok

    return scores, pages


def main() -> None:
    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    records = payload["records"]
    metadata = {
        index: json.loads((META_DIR / f"{index}.json").read_text(encoding="utf-8"))
        for index in range(1, 51)
    }
    scored: list[tuple[dict[str, Any], dict[str, bool], dict[str, bool]]] = []
    for record in records:
        gold = metadata[int(record["id"])] ["gold"]
        scores, pages = score_document(gold, record["result"])
        scored.append((record, scores, pages))

    counts = {field: sum(scores[field] for _, scores, _ in scored) for field in FIELDS}
    vat_value_count = sum(
        vat_value_equal(record["result"].get("vat") or {}, metadata[int(record["id"])] ["gold"]["vat"])
        for record, _, _ in scored
    )
    vat_mode_count = sum(
        vat_mode_equal(
            (record["result"].get("vat") or {}).get("mode"),
            metadata[int(record["id"])] ["gold"]["vat"].get("mode"),
        )
        for record, _, _ in scored
    )
    page_counts = {}
    for _, _, pages in scored:
        for field, value in pages.items():
            page_counts.setdefault(field, [0, 0])
            page_counts[field][0] += int(value)
            page_counts[field][1] += 1

    latencies = [float(record["elapsed_sec"]) for record in records]
    quantiles = statistics.quantiles(latencies, n=20, method="inclusive")
    summary = {
        "documents": len(records),
        "inference_success": sum(record["status"] in {"ok", "ok_unlabeled"} for record in records),
        "inference_errors": sum(record["status"] == "error" for record in records),
        "normalized_value_metrics": {
            "strict_document_accuracy": sum(all(scores.values()) for _, scores, _ in scored) / len(scored),
            "mean_field_accuracy": sum(counts.values()) / (len(scored) * len(FIELDS)),
            "field_accuracy": {
                field: {"correct": counts[field], "total": len(scored), "accuracy": counts[field] / len(scored)}
                for field in FIELDS
            },
        },
        "vat_component_metrics": {
            "value_accuracy": {"correct": vat_value_count, "total": len(scored), "accuracy": vat_value_count / len(scored)},
            "mode_accuracy": {"correct": vat_mode_count, "total": len(scored), "accuracy": vat_mode_count / len(scored)},
            "combined_accuracy": {"correct": counts["vat"], "total": len(scored), "accuracy": counts["vat"] / len(scored)},
        },
        "page_number_metrics": {
            field: {"correct": values[0], "total": values[1], "accuracy": values[0] / values[1]}
            for field, values in sorted(page_counts.items())
        },
        "latency_sec": {
            "total": round(sum(latencies), 1),
            "mean": round(statistics.mean(latencies), 1),
            "median": round(statistics.median(latencies), 1),
            "p95": round(quantiles[18], 1),
            "max": round(max(latencies), 1),
            "slowest_docs": sorted(
                [(int(record["id"]), float(record["elapsed_sec"])) for record in records],
                key=lambda item: item[1],
                reverse=True,
            )[:5],
        },
        "mismatch_documents": [
            int(record["id"])
            for record, scores, _ in scored
            if not all(scores.values())
        ],
    }
    METRICS_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
