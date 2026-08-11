from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any


RESULTS_PATH = Path("tmp/eval_50_results.json")
META_PATH = Path("dataset/meta.json")

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


def number_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", text)
    return float(match.group()) if match else None


def vat_ok(gold: Any, predicted: Any) -> bool:
    if not isinstance(predicted, dict):
        return False
    gold_text = norm(gold)
    mode = norm(predicted.get("mode"))
    rate = number_value(predicted.get("rate"))
    raw = norm(predicted.get("raw_value"))
    evidence = norm(predicted.get("evidence"))
    if "без ндс" in gold_text:
        return mode == "not_subject" or "без ндс" in raw or "без ндс" in evidence
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*%", gold_text)
    if match:
        return rate is not None and rate == float(match.group(1).replace(",", "."))
    if gold_text == "0":
        return rate == 0 or mode == "not_subject"
    return norm(predicted.get("raw_value")) == gold_text


def semantic_score(meta: dict[str, Any], result: dict[str, Any]) -> dict[str, bool]:
    def obj(field: str) -> dict[str, Any]:
        value = result.get(field)
        return value if isinstance(value, dict) else {}

    parties = [item for item in result.get("parties", []) if isinstance(item, dict)]
    names = [canonical_name(item.get("name")) for item in parties]
    inns = [norm(item.get("inn")) for item in parties]
    term = obj("term")
    predicted_term = date_value(term.get("value")) or date_value(term.get("evidence"))
    return {
        "contract_number": norm(obj("contract_number").get("value")) == norm(meta.get("number")),
        "contract_date": date_value(obj("contract_date").get("value")) == date_value(meta.get("date")),
        "contract_type": norm(obj("contract_type").get("value")) == norm(meta.get("contract_type")),
        "place": norm(obj("place").get("value")) == norm(meta.get("place")),
        "term": predicted_term == date_value(meta.get("term")),
        "party1_name": canonical_name(meta.get("party1")) in names,
        "party2_name": canonical_name(meta.get("party2")) in names,
        "party1_inn": norm(meta.get("inn1")) in inns,
        "party2_inn": norm(meta.get("inn2")) in inns if meta.get("inn2") else True,
        "total_amount": number_value(obj("total_amount").get("value")) == number_value(meta.get("amount")),
        "vat": vat_ok(meta.get("vat"), result.get("vat")),
    }


def main() -> None:
    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    records = payload["records"]
    labeled = [record for record in records if isinstance(record.get("field_scores"), dict)]
    fields = list(labeled[0]["field_scores"])
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
    metadata_by_id = {int(item["id"]): item["meta"] for item in metadata}
    semantic_scores = [
        (record, semantic_score(metadata_by_id[int(record["id"])], record["result"]))
        for record in labeled
    ]
    exact_counts = {
        field: sum(bool(record["field_scores"][field]) for record in labeled)
        for field in fields
    }
    semantic_counts = {
        field: sum(bool(scores[field]) for _, scores in semantic_scores)
        for field in fields
    }
    latencies = [float(record["elapsed_sec"]) for record in records]
    quantiles = statistics.quantiles(latencies, n=20, method="inclusive")

    summary = {
        "documents": len(records),
        "inference_success": sum(record["status"] in {"ok", "ok_unlabeled"} for record in records),
        "inference_errors": sum(record["status"] == "error" for record in records),
        "labeled_documents": len(labeled),
        "unlabeled_documents": len(records) - len(labeled),
        "exact_string_metrics_on_labeled": {
            "strict_document_accuracy": sum(bool(record["all_fields_ok"]) for record in labeled) / len(labeled),
            "mean_field_accuracy": sum(exact_counts.values()) / (len(labeled) * len(fields)),
            "field_accuracy": {
                field: {"correct": exact_counts[field], "total": len(labeled), "accuracy": exact_counts[field] / len(labeled)}
                for field in fields
            },
        },
        "semantic_normalized_metrics_on_labeled": {
            "strict_document_accuracy": sum(all(scores.values()) for _, scores in semantic_scores) / len(labeled),
            "mean_field_accuracy": sum(semantic_counts.values()) / (len(labeled) * len(fields)),
            "field_accuracy": {
                field: {"correct": semantic_counts[field], "total": len(labeled), "accuracy": semantic_counts[field] / len(labeled)}
                for field in fields
            },
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
        "semantic_mismatch_documents": [
            int(record["id"])
            for record, scores in semantic_scores
            if not all(scores.values())
        ],
    }
    Path("tmp/eval_50_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
