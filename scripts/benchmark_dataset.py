"""Resumable, identical-input full-corpus comparison. Reports contain private data."""

from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import time

from dotenv import load_dotenv

from src.evaluation import FIELDS, score_gold, score_pages, vat_components, summarize
from src.evaluation_labels import load_labels

FILE_PATTERN = re.compile(r"^Договор_(\d+)\.(pdf|docx|png)$", re.IGNORECASE)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_hash() -> str:
    files = [*Path("src/extraction").glob("*.py"), Path("src/parsing.py"), Path("src/pdf_parser.py"), Path("src/ocr.py"), Path("backend/extraction.py"), Path("backend/document_view.py"), Path("src/evaluation.py"), Path("src/evaluation_labels.py"), Path("scripts/benchmark_dataset.py")]
    return digest(b"".join(path.as_posix().encode() + path.read_bytes() for path in sorted(files)))


def apply_scores(record, gold):
    record['labeled'] = gold is not None
    record['field_scores'] = (score_gold(gold, record['fields']) if record['status'] == 'ok' else {key: False for key in FIELDS}) if gold is not None else None
    record['vat_components'] = None
    record['page_scores'] = None
    if gold and 'gold' in gold:
        record['vat_components'] = vat_components(gold, record.get('fields') or {}) if record['status'] == 'ok' else {key: False for key in ('value','mode','combined')}
        if record['format'] == 'pdf':
            record['page_scores'] = score_pages(gold, record.get('fields') or {})


def require_label_coverage(labels, contract_ids, allow_unlabeled=False):
    absent = sorted(set(contract_ids) - set(labels))
    if absent and not allow_unlabeled:
        raise ValueError(f'Missing labels for contract IDs {absent}; select the complete meta directory or explicitly pass --allow-unlabeled')


def prepare(args) -> None:
    from src.extraction.pipeline import extract_text_from_document
    from backend.document_view import view_pdf_path
    from src.document_ir import SourceFormat

    files = sorted((path for path in args.dataset.iterdir() if FILE_PATTERN.match(path.name)), key=lambda path: (int(FILE_PATTERN.match(path.name)[1]), path.suffix))
    if not files:
        raise FileNotFoundError(f"No contract documents in {args.dataset}")
    labels, label_source = load_labels(args.labels)
    require_label_coverage(labels, [int(FILE_PATTERN.match(path.name)[1]) for path in files], getattr(args, 'allow_unlabeled', False))
    manifest_path = args.output / "manifest.json"
    manifest = {"code_hash": code_hash(), "label_hash": label_source["sha256"], "label_source": label_source,
                "created_at": datetime.now(timezone.utc).isoformat(), "files": [], "labels": labels}
    for index, source in enumerate(files, start=1):
        match = FILE_PATTERN.match(source.name)
        entry = {"document_id": int(match[1]), "format": match[2].lower(), "filename": source.name,
                 "source_hash": digest(source.read_bytes()), "labeled": int(match[1]) in labels}
        cache = args.output / "cache" / (source.name + ".json")
        started = time.perf_counter()
        try:
            cached = json.loads(cache.read_text()) if cache.is_file() else None
            if cached and cached.get("source_hash") == entry["source_hash"] and cached.get("code_hash") == manifest["code_hash"]:
                entry.update(cached["entry"])
            else:
                parse_path = source
                if entry["format"] == "docx":
                    copy = args.output / "converted" / source.name
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, copy)
                    parse_path = view_pdf_path(copy)
                text, ir = extract_text_from_document(parse_path)
                if entry["format"] == "docx":
                    ir.source_format = SourceFormat.DOCX
                    ir.source_path = str(source.resolve())
                entry.update(status="ready", input_hash=digest(text.encode()), text_chars=len(text), pages=len(ir.pages),
                             ocr_pages=sum(page.needs_ocr for page in ir.pages), parsing_sec=round(time.perf_counter() - started, 3), warnings=ir.warnings)
                write_json(cache, {"source_hash": entry["source_hash"], "code_hash": manifest["code_hash"], "entry": entry, "text": text, "ir": ir.model_dump(mode="json")})
            entry["cache"] = str(cache.resolve())
        except Exception as exc:
            entry.update(status="parse_error", error_type=type(exc).__name__)
        manifest["files"].append(entry)
        write_json(manifest_path, manifest)
        print(f"parse {index}/{len(files)} id={entry['document_id']} {entry['format']} {entry['status']}", flush=True)
    manifest["completed"] = True
    manifest["inventory"] = {"files": len(files), "contracts": len({item["document_id"] for item in manifest["files"]}),
                             "formats": dict(Counter(item["format"] for item in manifest["files"])), "labeled_files": sum(item["labeled"] for item in manifest["files"]),
                             "labeled_contracts": len({item["document_id"] for item in manifest["files"] if item["labeled"]}), "parse_errors": sum(item["status"] != "ready" for item in manifest["files"])}
    write_json(manifest_path, manifest)
    print(json.dumps(manifest["inventory"], ensure_ascii=False), flush=True)


def run(args) -> None:
    from backend.config import Settings
    from backend.extraction import ExtractionService
    from src.document_ir import DocumentIR
    from src.extraction.api_models import preflight_model, safe_error_details
    from src.extraction.model_loading import unload_model

    manifest = json.loads((args.output / "manifest.json").read_text())
    if not manifest.get("completed") or manifest["code_hash"] != code_hash():
        raise RuntimeError("Parsing manifest is incomplete or ML code changed; prepare a fresh run")
    if args.backend == "api" and not args.allow_external_data:
        raise RuntimeError("API corpus run requires explicit --allow-external-data")
    os.environ.update(ML_ALLOW_EXTERNAL="true" if args.backend == "api" else "false", ML_KEEP_MODELS_LOADED="true",
                      ML_HF_FALLBACK_ENABLED="false", HF_HUB_OFFLINE="1", DEEPCODE_ENABLE_THINKING="false",
                      EXTRACTION_API_PROVIDER="deepcode", EXTRACTION_API_MODEL=args.api_model,
                      EXTRACTION_API_MAX_NEW_TOKENS="4096", EXTRACTION_CHUNK_CHARS="12000")
    if args.backend == "api":
        args.api_model = preflight_model(args.api_model)
        os.environ["EXTRACTION_API_MODEL"] = args.api_model
    settings = Settings(_env_file=None, extraction_backend=args.backend)
    service = ExtractionService(settings)
    path = args.output / f"{args.backend}.json"
    if path.is_file() and not args.resume:
        raise FileExistsError(f"{path} already exists; use --resume or a new output directory")
    config = {"backend": args.backend, "api_model": args.api_model if args.backend == "api" else None,
              "code_hash": manifest["code_hash"], "label_hash": manifest["label_hash"], "insights": args.insights,
              "thinking": False, "chunk_chars": 12000, "max_new_tokens": 4096, "label_format": manifest.get("label_source", {}).get("format", "legacy")}
    report = json.loads(path.read_text()) if args.resume and path.is_file() else {"config": config, "records": [], "started_at": datetime.now(timezone.utc).isoformat(), "machine": platform.machine()}
    if report["config"] != config:
        raise RuntimeError("Cannot resume with different models, inputs, code or configuration")
    done = {(item["document_id"], item["format"]) for item in report["records"]}
    pending = [item for item in manifest["files"] if (item["document_id"], item["format"]) not in done]

    def process(entry):
        gold = manifest["labels"].get(str(entry["document_id"]))
        record = {key: entry.get(key) for key in ("document_id", "format", "filename", "input_hash", "parsing_sec", "pages", "text_chars", "ocr_pages", "labeled")}
        if entry["status"] != "ready":
            record.update(status="parse_error", field_scores={key: False for key in FIELDS} if gold else None)
            apply_scores(record, gold)
            return record
        cached = json.loads(Path(entry["cache"]).read_text())
        text = cached["text"]
        if digest(text.encode()) != entry["input_hash"]:
            raise RuntimeError("Parsed input hash mismatch")
        ir = DocumentIR.model_validate(cached["ir"])
        started = time.perf_counter()
        try:
            fields, usage = service.extract(text=text, document_ir=ir)
            record.update(status="ok", fields=fields, usage=usage, field_scores=score_gold(gold, fields) if gold else None)
        except Exception as exc:
            # No raw exception string is written to stdout; reports are private.
            record.update(status="error", **safe_error_details(exc), field_scores={key: False for key in FIELDS} if gold else None)
        record["extraction_sec"] = round(time.perf_counter() - started, 3)
        record["inference_executed"] = True
        if args.insights and args.backend == "api" and record["status"] == "ok":
            from src.extraction.summary import summarize_document
            from src.extraction.risks import analyze_risks
            from src.extraction.context import evidence_pages
            insight = {"errors": []}
            started = time.perf_counter()
            try:
                insight["summary"] = summarize_document(text, record["fields"], max_input_chars=12000, max_new_tokens=800)
            except Exception as exc:
                insight["errors"].append({"stage": "summary", **safe_error_details(exc)})
            try:
                insight["risks"] = analyze_risks(text, record["fields"])
                insight["pages_grounded"] = all(item["page"] in evidence_pages(text, item["evidence"]) for item in insight["risks"] if item["page"] is not None)
            except Exception as exc:
                insight["errors"].append({"stage": "risks", **safe_error_details(exc)})
            insight.update(status="error" if insight["errors"] else "ok", elapsed_sec=round(time.perf_counter() - started, 3), semantic_accuracy=None)
            record["insights"] = insight
        apply_scores(record, gold)
        return record

    if args.insights and args.backend == "api":
        os.environ.update(SUMMARY_BACKEND="api", RISK_BACKEND="api", SUMMARY_PROVIDER="deepcode", RISK_PROVIDER="deepcode",
                          SUMMARY_MODEL_NAME=args.api_model, RISK_MODEL_NAME=args.api_model, RISK_MAX_NEW_TOKENS="2000", RISK_MAX_INPUT_CHARS="12000")
    report["completed"] = False
    write_json(path, report)

    def collect(record):
        report["records"].append(record)
        report["summary"] = summarize(report["records"])
        write_json(path, report)
        checks = record.get("field_scores")
        passed = sum(value is True for value in checks.values()) if checks is not None else None
        print(f"{args.backend} {len(report['records'])}/{len(manifest['files'])} id={record['document_id']} {record['format']} {record['status']} fields={passed if passed is not None else 'unlabeled'}/11 sec={record.get('extraction_sec', 0)}", flush=True)

    previous_by_hash = {item["input_hash"]: item for item in report["records"] if item.get("input_hash") and item.get("status") == "ok"}
    grouped = defaultdict(list)

    def reuse(reference, entry):
        record = deepcopy(reference)
        record.update({key: entry.get(key) for key in ("document_id", "format", "filename", "input_hash", "parsing_sec", "pages", "text_chars", "ocr_pages", "labeled")})
        record.update(reused_from=reference["filename"], reference_extraction_sec=reference.get("extraction_sec"), extraction_sec=None, inference_executed=False)
        gold = manifest["labels"].get(str(entry["document_id"]))
        apply_scores(record, gold)
        collect(record)

    for entry in pending:
        if entry.get("input_hash") in previous_by_hash:
            reuse(previous_by_hash[entry["input_hash"]], entry)
        else:
            grouped[entry.get("input_hash") or entry["filename"]].append(entry)

    def collect_group(record, entries):
        collect(record)
        for entry in entries[1:]:
            if record["status"] == "ok":
                reuse(record, entry)
            else:
                collect(process(entry))  # Do not propagate transient failures to duplicates.

    try:
        if args.backend == "api" and args.workers > 1:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(process, entries[0]): entries for entries in grouped.values()}
                for future in as_completed(futures):
                    collect_group(future.result(), futures[future])
        else:
            for entries in grouped.values():
                entry = entries[0]
                print(f"start {args.backend} id={entry['document_id']} {entry['format']}", flush=True)
                collect_group(process(entry), entries)
        report["completed"] = True
    finally:
        report["summary"] = summarize(report["records"])
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, report)
        if args.backend == "local":
            unload_model()


def compare(args) -> None:
    reports = {backend: json.loads((args.output / f"{backend}.json").read_text()) for backend in ("local", "api")}
    local, api = reports["local"], reports["api"]
    if (local["config"]["code_hash"] != api["config"]["code_hash"] or local["config"]["label_hash"] != api["config"]["label_hash"]
            or local["config"].get("scoring_code_hash") != api["config"].get("scoring_code_hash")):
        raise RuntimeError("Cannot compare different runtime snapshots or labels")
    joined = defaultdict(dict)
    for backend, report in reports.items():
        for item in report["records"]:
            joined[(item["document_id"], item["format"])][backend] = item
    paired = []
    disagreements = []
    clusters = defaultdict(lambda: {"local_correct": 0, "api_correct": 0, "total": 0})
    for (document_id, format_name), items in sorted(joined.items()):
        if len(items) != 2:
            continue
        if items["local"].get("input_hash") != items["api"].get("input_hash"):
            raise RuntimeError("Models received different text")
        pair = {"document_id": document_id, "format": format_name}
        for backend in ("local", "api"):
            checks = items[backend].get("field_scores")
            pair[backend] = sum(value is True for value in checks.values()) if checks is not None else None
        if pair["local"] is not None:
            paired.append(pair)
            shared = [key for key in FIELDS if items["local"]["field_scores"].get(key) is not None and items["api"]["field_scores"].get(key) is not None]
            for key in shared:
                clusters[document_id]["total"] += 1
                for backend in ("local", "api"):
                    clusters[document_id][backend + "_correct"] += bool(items[backend]["field_scores"][key])
            differences = [key for key in FIELDS if items["local"]["field_scores"].get(key) != items["api"]["field_scores"].get(key)]
            if differences:
                disagreements.append({"document_id": document_id, "format": format_name, "fields": differences})
    rng = random.Random(42)
    values = list(clusters.values())
    deltas = []
    for _ in range(2000 if values else 0):
        sample = rng.choices(values, k=len(values))
        deltas.append(sum(item["api_correct"] - item["local_correct"] for item in sample) / sum(item["total"] for item in sample))
    deltas.sort()
    result = {"completed": all(report.get("completed") for report in reports.values()),
              "summary": {backend: report["summary"] for backend, report in reports.items()},
              "per_format": {backend: {fmt: summarize([item for item in report["records"] if item["format"] == fmt]) for fmt in ("pdf", "docx", "png")} for backend, report in reports.items()},
              "paired_files": len(paired), "api_better_files": sum(item["api"] > item["local"] for item in paired),
              "local_better_files": sum(item["local"] > item["api"] for item in paired), "tied_files": sum(item["api"] == item["local"] for item in paired),
              "paired_cluster_bootstrap_api_minus_local_95_ci": [deltas[50], deltas[1949]] if deltas else None,
              "contract_macro_accuracy": {backend: sum(item[backend + "_correct"] / item["total"] for item in values) / len(values) if values else None for backend in ("local", "api")},
              "vat_components": {backend: {component: {"correct": sum(bool(item["vat_components"][component]) for item in report["records"] if item.get("vat_components") is not None), "total": sum(item.get("vat_components") is not None for item in report["records"])} for component in ("value", "mode", "combined")} for backend, report in reports.items()},
              "pdf_page_scores": {backend: {field: {"correct": sum(bool((item.get("page_scores") or {}).get(field)) for item in report["records"] if field in (item.get("page_scores") or {})), "total": sum(field in (item.get("page_scores") or {}) for item in report["records"])} for field in FIELDS} for backend, report in reports.items()},
              "disagreements": disagreements,
              "limitations": [f"{len(paired)} labeled file variants covering {len(clusters)} contract IDs; file variants are not independent contracts.",
                              "Legacy VAT 0 is ambiguous; structured gold scores VAT value and mode together. See label_format in the source reports.",
                              "Accuracy measures the full postprocessed pipeline, not raw model output.",
                              "No gold summaries/risks: insight metrics establish execution and citation grounding, not semantic accuracy."]}
    write_json(args.output / "comparison.json", result)
    print(json.dumps({"completed": result["completed"], "paired_files": len(paired), "field_accuracy": {backend: item["field_accuracy"] for backend, item in result["summary"].items()}}, ensure_ascii=False), flush=True)


def rescore(args) -> None:
    if args.source_results is None or args.source_results.resolve() == args.output.resolve():
        raise ValueError("Use --source-results and a separate --output; original inference must remain immutable")
    if (args.output / "manifest.json").exists():
        raise FileExistsError("Rescore output already exists; choose a new directory")
    labels, label_source = load_labels(args.labels)
    source = args.source_results
    manifest = json.loads((source / "manifest.json").read_text())
    if not manifest.get("completed"):
        raise ValueError("Source manifest is incomplete")
    entries = {(item["document_id"], item["format"]): item for item in manifest["files"]}
    require_label_coverage(labels, [item['document_id'] for item in manifest['files']], getattr(args, 'allow_unlabeled', False))
    rewritten = deepcopy(manifest)
    rewritten.update(labels=labels, label_hash=label_source['sha256'], label_source=label_source,
                     inference_manifest_sha256=digest((source / "manifest.json").read_bytes()),
                     scoring_code_hash=code_hash())
    for item in rewritten['files']:
        item['labeled'] = item['document_id'] in labels
    rewritten['inventory']['labeled_contracts'] = len(set(labels) & {item['document_id'] for item in rewritten['files']})
    rewritten['inventory']['labeled_files'] = sum(item['labeled'] for item in rewritten['files'])
    reports = {}
    for backend in ('local', 'api'):
        original = json.loads((source / f'{backend}.json').read_text())
        if not original.get('completed'):
            raise ValueError(f'{backend} inference is incomplete')
        report = deepcopy(original)
        report['config'].update(label_hash=label_source['sha256'], label_format=label_source['format'],
                                source_label_hash=original['config']['label_hash'], scoring_code_hash=code_hash(),
                                inference_report_sha256=digest((source / f'{backend}.json').read_bytes()),
                                rescored_from=str(source.resolve()))
        report['label_source'] = label_source
        for record in report['records']:
            entry = entries[(record['document_id'], record['format'])]
            if record.get('input_hash') != entry.get('input_hash'):
                raise ValueError('Saved inference input hash mismatch')
            gold = labels.get(record['document_id'])
            apply_scores(record, gold)
        report['summary'] = summarize(report['records'])
        report['rescored_at'] = datetime.now(timezone.utc).isoformat()
        reports[backend] = report
    write_json(args.output / 'manifest.json', rewritten)
    for backend, report in reports.items():
        write_json(args.output / f'{backend}.json', report)
    compare(args)


def main() -> None:
    load_dotenv()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "run", "compare", "rescore"])
    parser.add_argument("--labels", type=Path, default=Path("meta"))
    parser.add_argument("--allow-unlabeled", action="store_true", help="Explicitly permit incomplete gold coverage")
    parser.add_argument("--source-results", type=Path, help="Immutable completed inference run for rescore")
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--output", type=Path, default=Path("tmp/full-comparison-2026-10-26"))
    parser.add_argument("--backend", choices=["local", "api"], default="local")
    parser.add_argument("--api-model", default="qwen3.8-flash-next")
    parser.add_argument("--allow-external-data", action="store_true")
    parser.add_argument("--insights", action="store_true")
    parser.add_argument("--workers", type=int, choices=[1, 2, 3, 4], default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "compare": compare, "rescore": rescore}[args.stage](args)


if __name__ == "__main__":
    main()
