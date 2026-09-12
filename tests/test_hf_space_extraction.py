from __future__ import annotations

import json

from src.hf_space_extraction import HFSpaceNuExtractBackend


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def predict(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return (
            "",
            "{'value': '```json\\n{\\\"contract_type\\\": {\\\"value\\\": \\\"Договор поставки\\\"}}\\n```', '__type__': 'update'}",
            "done",
        )


def test_hf_space_backend_calls_extraction_endpoint_and_parses_json() -> None:
    client = FakeClient()
    backend = HFSpaceNuExtractBackend(client=client)

    extracted = backend.extract_fields_from_text("Договор поставки от 01.01.2026")

    assert extracted.result["contract_type"]["value"] == "Договор поставки"
    assert extracted.usage.input_chars > 0
    assert extracted.usage.output_chars > 0
    assert extracted.usage.status_text == "done"
    args, kwargs = client.calls[0]
    assert kwargs["api_name"] == "/on_extract_click"
    assert args[2] == "Договор поставки от 01.01.2026"
    assert json.loads(args[1])["contract_type"]["value"]


def test_hf_space_backend_rejects_empty_text() -> None:
    backend = HFSpaceNuExtractBackend(client=FakeClient())

    try:
        backend.extract_fields_from_text(" ")
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("empty text should be rejected")
