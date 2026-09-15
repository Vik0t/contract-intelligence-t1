from __future__ import annotations

from types import SimpleNamespace

import backend.extraction as extraction_module
from backend.config import Settings
from backend.extraction import ExtractionService


def test_extraction_service_uses_local_backend_by_default(monkeypatch) -> None:
    calls = []

    def fake_extract_contract_key_data(**kwargs):
        calls.append(kwargs)
        return {"ok": True}, {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        }

    monkeypatch.setattr(
        extraction_module,
        "extract_contract_key_data",
        fake_extract_contract_key_data,
    )
    service = ExtractionService(
        Settings(_env_file=None, extraction_backend="local")
    )

    result, usage = service.extract(text="text")

    assert result == {"ok": True}
    assert usage["total_tokens"] == 3
    assert calls[0]["text"] == "text"


def test_extraction_service_routes_to_huggingface_space(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        extraction_backend="huggingface-space",
        hf_space_prompt_mode="compact",
        hf_space_context_mode="retrieved",
        hf_space_context_chars=3000,
        hf_space_reasoning=False,
    )
    service = ExtractionService(settings)

    class FakeBackend:
        def __init__(self):
            self.calls = []

        def extract_fields_from_text(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return SimpleNamespace(
                result={"contract_type": {"value": "Договор поставки"}},
                usage=SimpleNamespace(
                    estimated_input_tokens=10,
                    estimated_output_tokens=4,
                ),
            )

    fake_backend = FakeBackend()
    service._hf_space_backend = fake_backend

    result, usage = service.extract(text="document")

    assert result["contract_type"]["value"] == "Договор поставки"
    assert usage == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }
    _, kwargs = fake_backend.calls[0]
    assert kwargs["prompt_mode"] == "compact"
    assert kwargs["context_mode"] == "retrieved"
    assert kwargs["context_chars"] == 3000
    assert kwargs["reasoning"] is False
