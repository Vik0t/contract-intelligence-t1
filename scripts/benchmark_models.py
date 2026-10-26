"""Same synthetic contracts, timed extraction, no automatic model promotion."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import time

from dotenv import load_dotenv
from src.extraction.api_models import preflight_model, safe_error_details


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--backends", nargs="+", choices=["local", "api"], default=["local", "api"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--api-model", default=os.getenv("EXTRACTION_API_MODEL", "qwen3.8-flash-next"))
    parser.add_argument("--api-provider", default="deepcode")
    parser.add_argument("--insights", action="store_true", help="Also check summary and positive/negative risk controls using the API model")
    parser.add_argument("--output", type=Path, default=Path("tmp/model-comparison.json"))
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    # Selecting api explicitly authorizes only the synthetic fixtures in this script.
    uses_api = "api" in args.backends or args.insights
    if uses_api and not all(os.getenv(name) for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY")):
        parser.error("Задайте OPENAI_BASE_URL и OPENAI_API_KEY в .env")
    os.environ["ML_ALLOW_EXTERNAL"] = "true" if uses_api else "false"
    os.environ["ML_KEEP_MODELS_LOADED"] = "true"
    os.environ["ML_HF_FALLBACK_ENABLED"] = "false"
    os.environ["DEEPCODE_ENABLE_THINKING"] = "false"
    os.environ["EXTRACTION_API_MODEL"] = args.api_model
    os.environ["EXTRACTION_API_PROVIDER"] = args.api_provider
    os.environ["EXTRACTION_API_MAX_NEW_TOKENS"] = "4096"
    os.environ["EXTRACTION_CHUNK_CHARS"] = "12000"
    from backend.config import Settings
    from backend.extraction import ExtractionService
    from src.extraction.model_loading import unload_model, use_mlx, MODEL_ID
    from scripts.ml_check import TEXT, score

    cases = [
        ("supply", "PAGE 1\n" + TEXT, score),
        ("no_term", "PAGE 1\nДоговор поставки № 72 от 15.09.2026. ООО Альфа и ООО Бета заключили договор поставки оборудования. Срок действия и общая цена не указаны.",
         lambda result: {"no_fabricated_term": result["term"]["value"] is None, "no_fabricated_amount": result["total_amount"]["value"] is None}),
        ("late_term", "PAGE 1\nДоговор поставки № 73 от 15.09.2026.\n" + "Условия поставки согласуются сторонами.\n" * 450 + "\nPAGE 15\nДоговор действует до 31.12.2027.",
         lambda result: {"late_term": result["term"]["value"] == "2027-12-31", "late_page": result["term"]["page_number"] == 15}),
    ]
    local_model = os.getenv("CONTRACT_MLX_MODEL_ID", "numind/NuExtract3-mlx-8bits") if use_mlx() else MODEL_ID
    report = {"machine": platform.machine(), "system": platform.system(), "local_model": local_model, "api_model": args.api_model, "enable_thinking": False, "records": [], "limitations": ["Synthetic controls only; not a quality estimate on real legal contracts.", "First local request includes model loading; compare warm requests separately.", "Mac MLX timing cannot establish relative speed against a future H100/5090 deployment."]}

    def save_report():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)

    save_report()
    try:
        if uses_api:
            print("API: проверка доступа и имени модели…", flush=True)
            try:
                resolved = preflight_model(args.api_model)
                report["resolved_api_model"] = resolved
                os.environ["EXTRACTION_API_MODEL"] = resolved
                args.api_model = resolved
                report["api_preflight"] = {"passed": True}
            except Exception as exc:
                report["api_preflight"] = {"passed": False, **safe_error_details(exc)}
                report["passed"] = False
                print(json.dumps(report["api_preflight"], ensure_ascii=False), flush=True)
                print(f"Результаты: {args.output.resolve()}", flush=True)
                raise SystemExit(1)
        for backend in args.backends:
            service = ExtractionService(Settings(_env_file=None, extraction_backend=backend))
            for repeat in range(args.repeats):
                for name, text, scorer in cases:
                    started = time.perf_counter()
                    record = {"backend": backend, "case": name, "repeat": repeat, "passed": False}
                    print(f"{backend}: {name}, прогон {repeat + 1}/{args.repeats}…", flush=True)
                    try:
                        result, _usage = service.extract(text=text)
                        checks = scorer(result)
                        record.update(checks=checks, passed=all(checks.values()))
                        if repeat == 0 or not record["passed"]:
                            record["fields"] = result
                    except Exception as exc:
                        # Do not serialize HTTP exception strings that can include provider URLs.
                        record.update(safe_error_details(exc))
                    record["elapsed_sec"] = round(time.perf_counter() - started, 3)
                    report["records"].append(record)
                    save_report()
                    print(json.dumps({key: value for key, value in record.items() if key != "fields"}, ensure_ascii=False), flush=True)
                    if record.get("error_type"):
                        break
                if report["records"][-1].get("error_type"):
                    break
        if args.insights:
            if any(record.get("error_type") for record in report["records"] if record["backend"] == "api"):
                report["insights"] = {"passed": False, "status": "skipped_after_api_error"}
            else:
                os.environ.update(SUMMARY_BACKEND="api", RISK_BACKEND="api", SUMMARY_PROVIDER=args.api_provider,
                                  RISK_PROVIDER=args.api_provider, SUMMARY_MODEL_NAME=args.api_model, RISK_MODEL_NAME=args.api_model,
                                  RISK_MAX_NEW_TOKENS="2000")
                from src.extraction.summary import summarize_document
                from src.extraction.risks import analyze_risks
                controls = {"passed": False}
                print("API: проверка сводки и рисков…", flush=True)
                try:
                    started = time.perf_counter()
                    controls["summary"] = summarize_document("PAGE 1\n" + TEXT, {}, max_new_tokens=800)
                    controls["summary_elapsed_sec"] = round(time.perf_counter() - started, 3)
                    started = time.perf_counter()
                    controls["risks"] = analyze_risks("PAGE 1\n" + TEXT, {})
                    controls["risk_elapsed_sec"] = round(time.perf_counter() - started, 3)
                    neutral = "PAGE 1\nИзменения договора оформляются письменным соглашением обеих сторон. Ответственность определяется законодательством Российской Федерации."
                    controls["negative_risks"] = analyze_risks(neutral, {})
                    controls["checks"] = {
                        "summary_nonempty": bool(controls["summary"].strip()),
                        "price_change_detected": any("цен" in item["evidence"].casefold() for item in controls["risks"]),
                        "penalty_detected": any("неустой" in item["evidence"].casefold() for item in controls["risks"]),
                        "no_risks_in_negative_control": controls["negative_risks"] == [],
                    }
                    controls["passed"] = all(controls["checks"].values())
                except Exception as exc:
                    controls.update(safe_error_details(exc))
                report["insights"] = controls
                save_report()
        report["warm_median_sec"] = {
            backend: statistics.median(values) for backend in args.backends
            if (values := [record["elapsed_sec"] for record in report["records"] if record["backend"] == backend and record["repeat"] > 0 and not record.get("error_type")])
        }
        report["passed"] = all(record["passed"] for record in report["records"]) and report.get("insights", {"passed": True})["passed"]
    finally:
        try:
            unload_model()
        finally:
            save_report()
    print(f"Результаты: {args.output.resolve()}", flush=True)
    raise SystemExit(0 if report.get("passed") else 1)


if __name__ == "__main__":
    main()
