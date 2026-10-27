from __future__ import annotations

import json

import pytest

from src import hf_chat_extraction


def test_hf_chat_extraction_parses_and_postprocesses(monkeypatch) -> None:
    captured = {}

    def fake_chat(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return json.dumps(
            {"contract_number": {
                "value": "№ 42", "evidence": "Договор № 42", "page_number": 1
            }},
            ensure_ascii=False,
        )

    monkeypatch.setattr(hf_chat_extraction, "generate_chat", fake_chat)
    result, usage = hf_chat_extraction.extract_fields_with_hf_chat(
        "PAGE 1\nДоговор № 42", model="test-model"
    )

    assert result["contract_number"]["value"]
    assert usage["total_tokens"] > 0
    assert captured["kwargs"]["provider"] == "hf"
    assert "PAGE 1" in captured["prompt"]


def test_hf_chat_extraction_rejects_unrelated_json(monkeypatch) -> None:
    monkeypatch.setattr(hf_chat_extraction, "generate_chat", lambda *args, **kwargs: '{"ok": true}')
    with pytest.raises(ValueError, match="поля договора"):
        hf_chat_extraction.extract_fields_with_hf_chat("PAGE 1\nДоговор", model="test-model")
