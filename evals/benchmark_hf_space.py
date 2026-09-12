"""Benchmark NuExtract3 through the public Hugging Face Space.

Example:
    uv run python evals/benchmark_hf_space.py --document-id 2
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.document_ir import DocumentIR
from src.hf_space_extraction import (
    COMPACT_INSTRUCTIONS,
    HFSpaceNuExtractBackend,
    build_retrieved_context,
)
from src.local_extraction import CONTRACT_TEMPLATE, INSTRUCTIONS


def load_score_function():
    path = ROOT / "tests" / "analyze_50_new_meta.py"
    spec = importlib.util.spec_from_file_location("benchmark_scoring", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load scoring module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_document


def load_document(document_id: int) -> tuple[str, DocumentIR | None, dict[str, Any]]:
    with sqlite3.connect(ROOT / "documents.db") as connection:
        row = connection.execute(
            "SELECT text, document_ir FROM parsed_documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Parsed document {document_id} was not found")

    text, raw_ir = row
    document_ir = DocumentIR.model_validate(json.loads(raw_ir)) if raw_ir else None
    gold_path = ROOT / "meta" / f"{document_id}.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["gold"]
    return text, document_ir, gold


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark NuExtract3 through the public Hugging Face Space"
    )
    parser.add_argument("--document-id", type=int, default=2)
    parser.add_argument("--space-id", default="numind/NuExtract3")
    parser.add_argument("--api-name", default="/on_extract_click")
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="Enable Space reasoning; disabled by default for faster extraction",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=("production", "compact"),
        default="production",
        help="Use current project instructions or a shorter Space-compatible prompt",
    )
    parser.add_argument(
        "--context-mode",
        choices=("full", "retrieved"),
        default="full",
        help="Send the full document or page-aware keyword context",
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=5000,
        help="Maximum characters for retrieved context",
    )
    parser.add_argument(
        "--view-api",
        action="store_true",
        help="Print the Space API and exit",
    )
    parser.add_argument(
        "--allow-external-data",
        action="store_true",
        help="Explicitly allow sending project text/template to a public Space",
    )
    args = parser.parse_args()

    backend = HFSpaceNuExtractBackend(
        space_id=args.space_id,
        api_name=args.api_name,
    )
    if args.view_api:
        print(json.dumps(backend.view_api(), ensure_ascii=False, indent=2, default=str))
        return

    if not args.allow_external_data:
        parser.error(
            "Refusing to send project documents to a public Space. "
            "Pass --allow-external-data only after reviewing the privacy risk."
        )

    text, document_ir, gold = load_document(args.document_id)
    score_document = load_score_function()
    instructions = INSTRUCTIONS if args.prompt_mode == "production" else COMPACT_INSTRUCTIONS
    if args.context_chars < 1:
        parser.error("--context-chars must be positive")
    request_text = (
        text
        if args.context_mode == "full"
        else build_retrieved_context(text, max_chars=args.context_chars)
    )

    print(
        f"CONNECT space={args.space_id} api={args.api_name} "
        f"document={args.document_id} chars={len(text)}",
        flush=True,
    )
    started = time.perf_counter()
    try:
        extracted = backend.extract_fields_from_text(
            text,
            document_ir,
            instructions=instructions,
            template=CONTRACT_TEMPLATE,
            reasoning=args.reasoning,
            prompt_mode=args.prompt_mode,
            context_mode=args.context_mode,
            context_chars=args.context_chars,
        )
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", flush=True)
        raise

    total_elapsed = time.perf_counter() - started
    scores, pages = score_document(gold, extracted.result)
    result = {
        "backend": "huggingface-space",
        "space_id": args.space_id,
        "api_name": args.api_name,
        "document_id": args.document_id,
        "reasoning": args.reasoning,
        "prompt_mode": args.prompt_mode,
        "context_mode": args.context_mode,
        "document_chars": len(text),
        "request_chars": len(request_text),
        "total_elapsed_sec": round(total_elapsed, 3),
        "usage": extracted.usage.to_dict(),
        "fields_ok": sum(scores.values()),
        "fields_total": len(scores),
        "field_scores": scores,
        "page_scores": pages,
        "result": extracted.result,
        "raw_output": extracted.raw_output,
    }
    print(json.dumps({key: value for key, value in result.items() if key not in {"result", "raw_output"}}, ensure_ascii=False, indent=2), flush=True)

    output_path = ROOT / "evals" / f"benchmark_hf_space_doc_{args.document_id}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULTS {output_path}", flush=True)


if __name__ == "__main__":
    main()
