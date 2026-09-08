from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor, BitsAndBytesConfig

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.document_ir import DocumentIR
from src.local_extraction import (
    CONTRACT_TEMPLATE,
    INSTRUCTIONS,
    MODEL_ID,
    build_messages,
    parse_json_output,
    postprocess_extraction,
    validate_extraction,
)

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


def retrieved_text(text: str, max_chars: int = 4600) -> str:
    """Build a deterministic, page-aware context for a speed/quality experiment."""
    pages = re.split(r"(?=PAGE\s+\d+)", text)
    selected: list[str] = []
    keywords = re.compile(
        r"договор|сторон|заем|займ|срок|возврат|сумм|стоим|цен|инн|ндс|налог|постав|услуг|подряд",
        re.IGNORECASE,
    )
    for page in pages:
        if not page.strip():
            continue
        page_number = re.search(r"PAGE\s+(\d+)", page)
        if page_number and page_number.group(1) == "1":
            selected.append(page)
            continue
        matches = list(keywords.finditer(page))
        if not matches:
            continue
        fragments: list[str] = []
        for match in matches:
            start = max(0, match.start() - 180)
            end = min(len(page), match.end() + 260)
            fragments.append(page[start:end])
        compact = "\n".join(fragments)
        selected.append(f"{page_number.group(0) if page_number else ''}\n{compact}")

    result: list[str] = []
    total = 0
    for page in selected:
        remaining = max_chars - total
        if remaining <= 0:
            break
        result.append(page[:remaining])
        total += min(len(page), remaining)
    return "\n\n".join(result)


def load_variant(quantization: str, attention: str | None):
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    kwargs: dict[str, Any] = {
        "dtype": torch.bfloat16,
        "device_map": "cuda",
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
    }
    if quantization == "8bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_threshold=6.0,
        )
    elif quantization != "bf16":
        raise ValueError(f"Unknown quantization: {quantization}")
    if attention:
        kwargs["attn_implementation"] = attention
    model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, **kwargs).eval()
    return processor, model


def run_once(processor, model, text: str, document_ir: DocumentIR | None, max_new_tokens: int) -> dict[str, Any]:
    messages = build_messages(text)
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        template=json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False, indent=2),
        instructions=INSTRUCTIONS,
        enable_thinking=False,
    )
    prompt_tokens = int(inputs["input_ids"].shape[1])
    device = model.device
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}

    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            use_cache=True,
        )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    generated_ids = generated_ids[:, inputs["input_ids"].shape[1] :]
    completion_tokens = int(generated_ids.shape[1])
    raw = processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()
    parsed = parse_json_output(raw)
    parsed = postprocess_extraction(parsed, text)
    if document_ir is not None:
        parsed = validate_extraction(parsed, document_ir)
    return {
        "elapsed_sec": round(elapsed, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens_per_sec": round(completion_tokens / elapsed, 3) if elapsed else None,
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / (1024**3), 3) if torch.cuda.is_available() else None,
        "result": parsed,
    }


def unload(processor, model) -> None:
    del processor, model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare NuExtract inference configurations on one parsed document")
    parser.add_argument("--document-id", type=int, default=2)
    parser.add_argument(
        "--variants",
        default="all",
        help="Comma-separated variant names or 'all'",
    )
    args = parser.parse_args()

    text, document_ir, gold = load_document(args.document_id)
    contexts = {
        "full": text,
        "retrieved": retrieved_text(text),
    }
    score_document = load_score_function()
    all_variants = [
        ("8bit-full-1024", "8bit", None, "full", 1024),
        ("8bit-retrieved-1024", "8bit", None, "retrieved", 1024),
        ("8bit-sdpa-full-1024", "8bit", "sdpa", "full", 1024),
        ("bf16-full-1024", "bf16", None, "full", 1024),
        ("bf16-sdpa-full-1024", "bf16", "sdpa", "full", 1024),
    ]
    requested = {item.strip() for item in args.variants.split(",") if item.strip()}
    variants = all_variants if requested == {"all"} else [item for item in all_variants if item[0] in requested]
    unknown = requested - {item[0] for item in all_variants} - {"all"}
    if unknown:
        raise SystemExit(f"Unknown variants: {', '.join(sorted(unknown))}")
    results: list[dict[str, Any]] = []
    for name, quantization, attention, context_name, max_new_tokens in variants:
        print(f"START {name}: context_chars={len(contexts[context_name])}", flush=True)
        started = time.perf_counter()
        try:
            processor, model = load_variant(quantization, attention)
            load_time = time.perf_counter() - started
            measured = run_once(processor, model, contexts[context_name], document_ir, max_new_tokens)
            scores, pages = score_document(gold, measured["result"])
            measured.update(
                {
                    "variant": name,
                    "model_load_sec": round(load_time, 3),
                    "context": context_name,
                    "context_chars": len(contexts[context_name]),
                    "max_new_tokens": max_new_tokens,
                    "fields_ok": sum(scores.values()),
                    "fields_total": len(scores),
                    "page_scores": pages,
                }
            )
            results.append(measured)
            print(json.dumps({key: value for key, value in measured.items() if key != "result"}, ensure_ascii=False), flush=True)
            unload(processor, model)
        except Exception as exc:
            print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
            results.append({"variant": name, "error": f"{type(exc).__name__}: {exc}"})
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    output = ROOT / "evals" / f"benchmark_doc_{args.document_id}.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULTS {output}", flush=True)


if __name__ == "__main__":
    main()
