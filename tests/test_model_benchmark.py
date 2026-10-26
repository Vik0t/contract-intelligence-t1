import json
import sys

import pytest

from scripts import benchmark_models
from src.extraction import summary, risks
import backend.extraction


def test_comparison_writes_fields_and_insights_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(benchmark_models.os, "environ", benchmark_models.os.environ.copy())
    output = tmp_path / "comparison.json"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://test.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key-never-serialize")
    monkeypatch.setattr(sys, "argv", ["benchmark_models", "--backends", "api", "--api-model", "test-model", "--repeats", "1", "--insights", "--output", str(output)])
    monkeypatch.setattr(benchmark_models, "preflight_model", lambda model: model)

    class FakeService:
        def __init__(self, *_args):
            pass

        def extract(self, *, text):
            result = {name: {"value": value} for name, value in {
                "contract_number": "НГУ-2026-017", "contract_date": "2026-09-15",
                "contract_type": "Договор поставки", "place": "Новосибирск", "term": "2026-12-31", "total_amount": 100000,
            }.items()}
            result["vat"] = {"rate": 20, "mode": "included"}
            result["parties"] = [{"name": "ООО Альфа", "inn": "5406123456"}, {"name": "ООО Бета", "inn": "5406987654"}]
            if "№ 72" in text:
                result["term"]["value"] = result["total_amount"]["value"] = None
            if "№ 73" in text:
                result["term"] = {"value": "2027-12-31", "page_number": 15}
            return result, {}

    monkeypatch.setattr(backend.extraction, "ExtractionService", FakeService)
    monkeypatch.setattr(summary, "summarize_document", lambda *_args, **_kwargs: "Сводка договора поставки.")
    monkeypatch.setattr(risks, "analyze_risks", lambda text, *_args: [{"evidence": "изменение цены"}, {"evidence": "неустойка"}] if "неустойку" in text else [])
    with pytest.raises(SystemExit) as exit_info:
        benchmark_models.main()
    assert exit_info.value.code == 0
    raw = output.read_text()
    report = json.loads(raw)
    assert report["api_model"] == "test-model"
    assert len(report["records"]) == 3
    assert report["insights"]["passed"] is True
    assert report["passed"] is True
    assert "private-test-key" not in raw
    assert "test.invalid" not in raw
