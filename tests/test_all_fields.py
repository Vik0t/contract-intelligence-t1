''' Запуск:
    uv run tests/test.py --format docx --backend hf_space
'''

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.extraction.pipeline import extract_contract_key_data
from src.extraction.hf_space_pipeline import extract_contract_key_data_hf_space
from src.extraction.postprocess import _canonical_contract_type


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

def canon_contract_type(value: Any) -> str:
    text = norm(value)
    if not text:
        return ""
    canon = _canonical_contract_type(text)
    return norm(canon) if canon else text

def date_value(value: Any) -> str | None:
    """Парсит дату из предсказания модели в ISO-формат YYYY-MM-DD."""
    text = str(value or "")
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


def vat_ok(gold_vat: dict[str, Any], predicted: Any) -> bool:
    if not isinstance(predicted, dict):
        return False
    gold_mode = norm(gold_vat.get("mode"))
    gold_value = gold_vat.get("normalized_value")
    pred_mode = norm(predicted.get("mode"))
    pred_rate = number_value(predicted.get("rate"))
    raw = norm(predicted.get("raw_value"))
    evidence = norm(predicted.get("evidence"))

    if gold_mode in {"not_applicable", "not_subject"}:
        return (
            pred_mode in {"not_applicable", "not_subject"}
            or pred_rate == 0
            or "не облагается" in raw
            or "не облагается" in evidence
            or "без ндс" in raw
            or "без ндс" in evidence
        )
    if gold_value is not None:
        return pred_rate is not None and pred_rate == float(gold_value)
    return False


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


def score(gold: dict[str, Any], result: dict[str, Any]) -> dict[str, bool]:
    number = result.get("contract_number")
    date = result.get("contract_date")
    contract_type = result.get("contract_type")
    place = result.get("place")
    term = result.get("term")
    amount = result.get("total_amount")
    names, inns = party_values(result.get("parties"))

    gold_parties = sorted(gold.get("parties", []), key=lambda p: p.get("order", 0))
    gold_party1 = gold_parties[0] if len(gold_parties) > 0 else None
    gold_party2 = gold_parties[1] if len(gold_parties) > 1 else None

    pred_term = date_value(term.get("value") if isinstance(term, dict) else None)
    if pred_term is None and isinstance(term, dict):
        pred_term = date_value(term.get("evidence"))

    return {
        "contract_number": (
            isinstance(number, dict)
            and norm(number.get("value")) == norm(gold["contract_number"]["normalized_value"])
        ),
        "contract_date": (
            isinstance(date, dict)
            and date_value(date.get("value")) == gold["contract_date"]["normalized_value"]
        ),
        "contract_type": (
            isinstance(contract_type, dict)
            and canon_contract_type(contract_type.get("value"))
                == canon_contract_type(gold["contract_type"]["normalized_value"])
        ),
        "place": (
            isinstance(place, dict)
            and norm(place.get("value")) == norm(gold["place"]["normalized_value"])
        ),
        "term": pred_term == gold.get("term", {}).get("normalized_value"),
        "party1_name": (
            gold_party1 is not None
            and norm(gold_party1["name"]["normalized_value"]) in names
        ),
        "party2_name": (
            gold_party2 is not None
            and norm(gold_party2["name"]["normalized_value"]) in names
        ),
        "party1_inn": (
            gold_party1 is not None
            and norm(gold_party1["inn"]["normalized_value"]) in inns
        ),
        "party2_inn": (
            gold_party2 is None
            or norm(gold_party2["inn"]["normalized_value"]) in inns
        ),
        "total_amount": (
            isinstance(amount, dict)
            and number_value(amount.get("value")) == gold["total_amount"]["normalized_value"]
        ),
        "vat": vat_ok(gold.get("vat", {}), result.get("vat")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset", help="папка с файлами документов (docx/pdf/png)")
    parser.add_argument("--meta", default="meta/meta", help="папка с {id}.json разметкой")
    parser.add_argument(
        "--format",
        choices=["docx", "pdf", "png"],
        required=True,
        help="какой формат файлов прогонять в этом запуске",
    )
    parser.add_argument("--output", default=None, help="куда сохранить результаты (по умолчанию tmp/eval_50_results_<format>.json)")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument(
        "--backend",
        choices=["local", "hf_space"],
        default="local",
        help="local — локальная инференция NuExtract3, hf_space — через публичный HF Space",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    meta_dir = Path(args.meta)
    output_path = Path(args.output or f"tmp/eval_50_results_{args.format}_{args.backend}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ids = list(range(1, 51))
    records: list[dict[str, Any]] = []
    if args.resume and output_path.is_file():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        records = list(previous.get("records", []))
    processed_ids = {int(record["id"]) for record in records}
    run_started = datetime.now().astimezone().isoformat()
    run_start = time.perf_counter()

    hf_space_backend = None
    if args.backend == "hf_space":
        from src.hf_space_extraction import HFSpaceNuExtractBackend

        hf_space_backend = HFSpaceNuExtractBackend(connect_timeout=300.0)

    for position, doc_id in enumerate(ids, start=1):
        if doc_id in processed_ids:
            continue

        meta_path = meta_dir / f"{doc_id}.json"
        if not meta_path.is_file():
            print(f"[{position:02d}/50] {doc_id:03d}: нет файла разметки {meta_path}, пропуск", flush=True)
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        gold = meta.get("gold", {})

        filename = meta.get("files", {}).get(args.format)
        if not filename:
            print(f"[{position:02d}/50] {doc_id:03d}: нет формата {args.format} для этого документа, пропуск", flush=True)
            continue
        doc_path = dataset / filename
        if not doc_path.is_file():
            print(f"[{position:02d}/50] {doc_id:03d}: файл {doc_path} не найден на диске, пропуск", flush=True)
            continue

        started = time.perf_counter()
        record: dict[str, Any] = {"id": doc_id, "path": str(doc_path), "format": args.format}
        try:
            if args.backend == "local":
                result, _token_usage = extract_contract_key_data(
                    document=doc_path,
                    thinking=False,
                    max_new_tokens=args.max_new_tokens,
                )
            else:
                result = extract_contract_key_data_hf_space(document=doc_path, backend=hf_space_backend)
            elapsed = round(time.perf_counter() - started, 3)
            field_scores = score(gold, result)
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
            print(f"[{position:02d}/50] {doc_id:03d} ({args.format}): {passed}/11 fields, {elapsed:.1f}s", flush=True)
        except Exception as exc:  # Keep the run going after one failure.
            record.update(
                {
                    "status": "error",
                    "elapsed_sec": round(time.perf_counter() - started, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "field_scores": None,
                    "all_fields_ok": None,
                }
            )
            print(f"[{position:02d}/50] {doc_id:03d} ({args.format}): ERROR {type(exc).__name__}: {exc}", flush=True)

        records.append(record)
        output_path.write_text(
            json.dumps({"run_started": run_started, "records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    records.sort(key=lambda record: int(record["id"]))
    labeled_records = [r for r in records if isinstance(r.get("field_scores"), dict)]
    successful = [r for r in records if r["status"] == "ok"]
    field_counts = {
        field: sum(bool(record["field_scores"][field]) for record in labeled_records)
        for field in FIELD_NAMES
    }
    total_field_checks = len(labeled_records) * len(FIELD_NAMES) if labeled_records else 1

    summary = {
        "format": args.format,
        "documents": len(records),
        "labeled_documents": len(labeled_records),
        "successful_documents": len(successful),
        "failed_documents": len(records) - len(successful),
        "strict_document_accuracy": (
            sum(record["all_fields_ok"] for record in labeled_records) / len(labeled_records)
            if labeled_records else None
        ),
        "mean_field_accuracy": sum(field_counts.values()) / total_field_checks if labeled_records else None,
        "field_accuracy": {
            field: {
                "correct": count,
                "total": len(labeled_records),
                "accuracy": count / len(labeled_records) if labeled_records else None,
            }
            for field, count in field_counts.items()
        },
        "elapsed_total_sec": round(time.perf_counter() - run_start, 3),
        "elapsed_mean_sec": (
            round(sum(record["elapsed_sec"] for record in records) / len(records), 3) if records else None
        ),
        "errors": [
            {key: record[key] for key in ("id", "error_type", "error")}
            for record in records
            if record["status"] == "error"
        ],
    }
    output_path.write_text(
        json.dumps({"run_started": run_started, "summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()