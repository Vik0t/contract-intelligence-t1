"""Reproducible real-model acceptance check; synthetic data, no private contracts.

Run in the GPU container: python -m scripts.ml_check --output /reports/ml-check.json
This is a smoke/acceptance test, not a substitute for held-out legal evaluation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time

import pymupdf
from docx import Document

TEXT = """ДОГОВОР ПОСТАВКИ № НГУ-2026-017
г. Новосибирск
15.09.2026
ООО «Альфа», ИНН 5406123456, именуемое «Поставщик», и ООО «Бета», ИНН 5406987654, именуемое «Покупатель», заключили договор.
Предмет договора: поставка лабораторного оборудования.
Цена договора составляет 100 000 рублей, включая НДС 20%.
Договор действует до 31.12.2026.
Поставщик вправе в одностороннем порядке увеличить цену без ограничения размера повышения и без согласия Покупателя.
За каждый день просрочки оплаты Покупатель уплачивает неустойку 3% от всей цены договора без ограничения общей суммы.
Поставка оборудования осуществляется в течение 30 дней после оплаты.
"""
EXPECTED = {
    "contract_number": "НГУ-2026-017", "contract_date": "2026-09-15",
    "contract_type": "Договор поставки", "place": "Новосибирск", "term": "2026-12-31",
    "party1_name": "Альфа", "party2_name": "Бета", "party1_inn": "5406123456",
    "party2_inn": "5406987654", "total_amount": 100000, "vat": (20, "included"),
}


def fixtures(directory: Path) -> dict[str, Path]:
    font_candidates = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/System/Library/Fonts/Supplemental/Arial.ttf")]
    font_path = next((item for item in font_candidates if item.is_file()), None)
    if not font_path:
        raise RuntimeError("Для тестового документа нужен шрифт DejaVu Sans или Arial с кириллицей")
    pdf_path = directory / "acceptance.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_font(fontname="contract", fontfile=str(font_path))
        remaining = page.insert_textbox(pymupdf.Rect(40, 40, 555, 802), TEXT, fontname="contract", fontsize=12)
        if remaining < 0:
            raise RuntimeError("Тестовый договор не поместился на страницу")
        pdf.save(pdf_path)
        page.get_pixmap(dpi=220).pil_save(str(directory / "acceptance.jpg"), format="JPEG", quality=90)
    doc = Document()
    for paragraph in TEXT.splitlines():
        doc.add_paragraph(paragraph)
    doc.save(directory / "acceptance.docx")
    return {name: directory / f"acceptance.{name}" for name in ("pdf", "docx", "jpg")}


def score(fields: dict) -> dict[str, bool]:
    parties = fields.get("parties") or []
    result = {}
    for key, expected in EXPECTED.items():
        if "_name" in key:
            result[key] = any(expected.casefold() in str(party.get("name") or "").casefold() for party in parties)
        elif "_inn" in key:
            result[key] = any(party.get("inn") == expected for party in parties)
        elif key == "vat":
            vat = fields.get(key) or {}
            result[key] = (vat.get("rate"), vat.get("mode")) == expected
        else:
            actual = (fields.get(key) or {}).get("value")
            result[key] = str(expected).casefold() in str(actual).casefold() if key in {"contract_number", "place"} else actual == expected
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tmp/ml-check.json"))
    parser.add_argument("--parsing-only", action="store_true")
    parser.add_argument("--backend", choices=["local", "api"], default="local")
    args = parser.parse_args()
    # Only an explicit --backend api enables external calls with synthetic data.
    os.environ.update(ML_ALLOW_EXTERNAL="true" if args.backend == "api" else "false", EXTRACTION_BACKEND=args.backend, SUMMARY_BACKEND=args.backend, RISK_BACKEND=args.backend)
    from backend.config import Settings
    from backend.extraction import ExtractionService
    from backend.document_view import view_pdf_path
    from src.extraction.pipeline import extract_text_from_document
    from src.extraction.summary import summarize_document
    from src.extraction.risks import analyze_risks
    from src.extraction.context import evidence_pages
    from scripts.check_runtime import check_runtime

    report = {"created_at": datetime.now(timezone.utc).isoformat(), "kind": "parsing" if args.parsing_only else "real_model_acceptance", "records": [], "limitations": ["Synthetic smoke test; held-out contracts and human review are required to establish accuracy."]}
    if not args.parsing_only:
        report["runtime"] = check_runtime(require_gpu=args.backend == "local", require_models=args.backend == "local")
    report["backend"] = args.backend
    service = ExtractionService(Settings(_env_file=None, extraction_backend=args.backend))
    with tempfile.TemporaryDirectory(prefix="contract-ml-check-") as temporary:
        for format_name, source in fixtures(Path(temporary)).items():
            started = time.perf_counter()
            record = {"format": format_name, "passed": False}
            try:
                parse_path = view_pdf_path(source) if format_name == "docx" else source
                text, document_ir = extract_text_from_document(parse_path)
                record.update(text_chars=len(text), pages=len(document_ir.pages), warnings=document_ir.warnings)
                parse_checks = [needle in re.sub(r"\s+", "", text) for needle in ("НГУ-2026-017", "100000", "31.12.2026")]
                record["parsing_checks"] = parse_checks
                if args.parsing_only:
                    record["passed"] = all(parse_checks)
                else:
                    fields, usage = service.extract(text=text, document_ir=document_ir)
                    summary = summarize_document(text, fields)
                    risks = analyze_risks(text, fields)
                    field_checks = score(fields)
                    record.update(field_checks=field_checks, fields_passed=sum(field_checks.values()), fields_total=len(field_checks), fields=fields, usage=usage, summary=summary, risks=risks)
                    record["risk_checks"] = {
                        "price_change_detected": any("цен" in item["evidence"].casefold() for item in risks),
                        "penalty_detected": any("неустой" in item["evidence"].casefold() for item in risks),
                        "pages_grounded": all(item["page"] in evidence_pages(text, item["evidence"]) for item in risks),
                    }
                    record["passed"] = all(parse_checks) and all(field_checks.values()) and bool(summary.strip()) and all(record["risk_checks"].values())
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            record["elapsed_sec"] = round(time.perf_counter() - started, 2)
            report["records"].append(record)
            print(json.dumps({key: record.get(key) for key in ("format", "passed", "elapsed_sec", "fields_passed", "error")}, ensure_ascii=False), flush=True)
        if not args.parsing_only:
            neutral = "PAGE 1\nПоставка осуществляется по согласованной сторонами спецификации. Изменения договора оформляются письменным соглашением обеих сторон. Ответственность определяется законодательством Российской Федерации."
            negative = {"format": "risk_negative_control", "passed": False}
            try:
                negative["risks"] = analyze_risks(neutral, {})
                negative["passed"] = negative["risks"] == []
            except Exception as exc:
                negative["error"] = f"{type(exc).__name__}: {exc}"
            report["records"].append(negative)
    report["passed"] = all(record["passed"] for record in report["records"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
