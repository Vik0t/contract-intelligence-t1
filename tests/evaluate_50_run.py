from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.local_extraction import extract_contract_key_data


FIELD_NAMES = [
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


def norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def date_value(value: Any) -> str | None:
    text = str(value or "")
    iso = re.findall(r"(?<!\d)(19|20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", text)
    if iso:
        # The first alternative is intentionally reparsed below because the
        # compact regex form also matches a four-digit year with a prefix.
        match = re.search(r"(?<!\d)((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", text)
        if match:
            year, month, day = map(int, match.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})(?!\d)", text)
    if match:
        day, month, year = map(int, match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def number_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").replace("\u00a0", " ").replace(" ", "")
    text = text.replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def vat_ok(gold: Any, predicted: Any) -> bool:
    gold_text = norm(gold)
    if not isinstance(predicted, dict):
        return False
    mode = norm(predicted.get("mode"))
    rate = number_value(predicted.get("rate"))
    raw = norm(predicted.get("raw_value"))
    evidence = norm(predicted.get("evidence"))
    if "без ндс" in gold_text:
        return mode == "not_subject" or "без ндс" in raw or "без ндс" in evidence
    percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%", gold_text)
    if percent:
        return rate is not None and rate == float(percent.group(1).replace(",", "."))
    if gold_text == "0":
        return (rate is not None and rate == 0) or mode == "not_subject"
    return norm(predicted.get("raw_value")) == gold_text


def party_values(predicted: Any) -> tuple[list[str], list[str]]:
    names: list[str] = []
    inns: list[str] = []
    if isinstance(predicted, list):
        for party in predicted:
            if not isinstance(party, dict):
                continue
            names.append(norm(party.get("name")))
            inns.append(norm(party.get("inn")))
    return names, inns


def score(meta: dict[str, Any], result: dict[str, Any]) -> dict[str, bool]:
    number = result.get("contract_number")
    date = result.get("contract_date")
    contract_type = result.get("contract_type")
    place = result.get("place")
    term = result.get("term")
    amount = result.get("total_amount")
    names, inns = party_values(result.get("parties"))

    gold_date = date_value(meta.get("date"))
    pred_term = date_value(term.get("value") if isinstance(term, dict) else None)
    if pred_term is None and isinstance(term, dict):
        pred_term = date_value(term.get("evidence"))

    return {
        "contract_number": isinstance(number, dict) and norm(number.get("value")) == norm(meta.get("number")),
        "contract_date": isinstance(date, dict) and date_value(date.get("value")) == gold_date,
        "contract_type": isinstance(contract_type, dict) and norm(contract_type.get("value")) == norm(meta.get("contract_type")),
        "place": isinstance(place, dict) and norm(place.get("value")) == norm(meta.get("place")),
        "term": pred_term == date_value(meta.get("term")),
        "party1_name": norm(meta.get("party1")) in names,
        "party2_name": norm(meta.get("party2")) in names,
        "party1_inn": norm(meta.get("inn1")) in inns,
        "party2_inn": norm(meta.get("inn2")) in inns if meta.get("inn2") else True,
        "total_amount": isinstance(amount, dict) and number_value(amount.get("value")) == number_value(meta.get("amount")),
        "vat": vat_ok(meta.get("vat"), result.get("vat")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset")
    parser.add_argument("--output", default="tmp/eval_50_results.json")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((dataset / "meta.json").read_text(encoding="utf-8"))
    if isinstance(metadata, dict) and "value" in metadata:
        metadata = metadata["value"]
    metadata_by_id = {int(item["id"]): item for item in metadata}
    ids = list(range(1, 51))
    records: list[dict[str, Any]] = []
    if args.resume and output_path.is_file():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        records = list(previous.get("records", []))
    processed_ids = {int(record["id"]) for record in records}
    run_started = datetime.now().astimezone().isoformat()
    run_start = time.perf_counter()

    for position, doc_id in enumerate(ids, start=1):
        if doc_id in processed_ids:
            continue
        pdf_path = dataset / f"Договор_{doc_id:03d}.pdf"
        started = time.perf_counter()
        record: dict[str, Any] = {"id": doc_id, "path": str(pdf_path)}
        try:
            result = extract_contract_key_data(
                document=pdf_path,
                thinking=False,
                max_new_tokens=args.max_new_tokens,
            )
            elapsed = round(time.perf_counter() - started, 3)
            if doc_id in metadata_by_id:
                field_scores = score(metadata_by_id[doc_id]["meta"], result)
                record.update(
                    {
                        "status": "ok",
                        "elapsed_sec": elapsed,
                        "field_scores": field_scores,
                        "all_fields_ok": all(field_scores.values()),
                        "result": result,
                    }
                )
                passed = sum(field_scores.values())
                print(f"[{position:02d}/50] {doc_id:03d}: {passed}/11 fields, {elapsed:.1f}s", flush=True)
            else:
                record.update(
                    {
                        "status": "ok_unlabeled",
                        "elapsed_sec": elapsed,
                        "field_scores": None,
                        "all_fields_ok": None,
                        "result": result,
                    }
                )
                print(f"[{position:02d}/50] {doc_id:03d}: processed (no gold labels), {elapsed:.1f}s", flush=True)
        except Exception as exc:  # Keep the 50-document run going after one failure.
            record.update(
                {
                    "status": "error",
                    "elapsed_sec": round(time.perf_counter() - started, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "field_scores": ({field: False for field in FIELD_NAMES} if doc_id in metadata_by_id else None),
                    "all_fields_ok": False,
                }
            )
            print(f"[{position:02d}/50] {doc_id:03d}: ERROR {type(exc).__name__}: {exc}", flush=True)
        records.append(record)
        output_path.write_text(
            json.dumps(
                {"run_started": run_started, "records": records},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    records.sort(key=lambda record: int(record["id"]))
    labeled_records = [
        record
        for record in records
        if isinstance(record.get("field_scores"), dict)
    ]
    successful = [record for record in records if record["status"] in {"ok", "ok_unlabeled"}]
    field_counts = {
        field: sum(bool(record["field_scores"][field]) for record in labeled_records)
        for field in FIELD_NAMES
    }
    total_field_checks = len(labeled_records) * len(FIELD_NAMES)
    summary = {
        "documents": len(records),
        "labeled_documents": len(labeled_records),
        "unlabeled_documents": len(records) - len(labeled_records),
        "successful_documents": len(successful),
        "failed_documents": len(records) - len(successful),
        "strict_document_accuracy_on_labeled": sum(record["all_fields_ok"] for record in labeled_records) / len(labeled_records),
        "mean_field_accuracy_on_labeled": sum(field_counts.values()) / total_field_checks,
        "field_accuracy": {
            field: {"correct": count, "total": len(labeled_records), "accuracy": count / len(labeled_records)}
            for field, count in field_counts.items()
        },
        "elapsed_total_sec": round(time.perf_counter() - run_start, 3),
        "elapsed_mean_sec": round(sum(record["elapsed_sec"] for record in records) / len(records), 3),
        "errors": [
            {key: record[key] for key in ("id", "error_type", "error")}
            for record in records
            if record["status"] == "error"
        ],
    }
    output_path.write_text(
        json.dumps(
            {"run_started": run_started, "summary": summary, "records": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
