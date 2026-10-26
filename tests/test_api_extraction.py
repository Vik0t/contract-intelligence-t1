import json

import pytest

from backend.config import Settings
from backend.extraction import ExtractionService
from src.extraction import chat_pipeline


def test_api_extraction_preserves_schema_and_verifies_sources(monkeypatch):
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "true")
    monkeypatch.setenv("EXTRACTION_API_MODEL", "test-deepcode-model")
    calls = []

    def generate(prompt, **kwargs):
        assert "JSON Schema:" in prompt
        assert '"$defs"' in prompt
        assert "vat.mode — строка или null" in prompt
        calls.append(kwargs)
        return json.dumps({"contract_number": {"value": "42", "evidence": "Договор № 42", "page_number": 99}})

    monkeypatch.setattr(chat_pipeline, "generate_chat", generate)
    result, usage = ExtractionService(Settings(_env_file=None, extraction_backend="api")).extract(text="PAGE 4\nДоговор № 42")
    assert result["contract_number"]["value"] == "42"
    assert result["contract_number"]["page_number"] == 4
    assert result["term"]["value"] is None
    assert calls[0]["model"] == "test-deepcode-model"
    assert calls[0]["provider"] == "deepcode"
    assert usage["total_tokens"] > 0


def test_api_extraction_cannot_bypass_local_only_policy(monkeypatch):
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "false")
    with pytest.raises(RuntimeError, match="Внешнее извлечение отключено"):
        ExtractionService(Settings(_env_file=None, extraction_backend="api")).extract(text="Договор")
