import json

import httpx
import pytest

from src.extraction import api_models, risks, summary


def test_internal_api_ignores_inherited_proxy_by_default(monkeypatch):
    monkeypatch.delenv("ML_API_TRUST_ENV", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy.example:9")
    with api_models.api_client() as client:
        assert client.trust_env is False
    monkeypatch.setenv("ML_API_TRUST_ENV", "true")
    with api_models.api_client() as client:
        assert client.trust_env is True


def test_connections_are_kept_between_analysis_stages_and_closed_on_shutdown():
    with api_models.api_client() as first:
        pass
    with api_models.api_client() as second:
        assert first is second
        assert not second.is_closed
    api_models.close_api_clients()
    assert first.is_closed


def test_risks_retry_invalid_citation_without_accepting_fabrication(monkeypatch):
    calls = []
    passage = "Поставщик вправе увеличить цену без согласия Покупателя."
    payload = {"title": "Изменение цены", "body": "Для покупателя цена может увеличиться.", "page": 1}

    def generate(prompt, **kwargs):
        calls.append(prompt)
        evidence = "Поставщик ... увеличивает цену" if len(calls) == 1 else passage
        return kwargs["parse"](json.dumps([{**payload, "evidence": evidence}], ensure_ascii=False))

    monkeypatch.setattr(risks, "generate_with_fallback", generate)
    result = risks.analyze_risks("PAGE 1\n" + passage, {})
    assert len(calls) == 2
    assert result[0]["evidence"] == passage
    assert result[0]["page"] == 1


def test_repeated_invalid_citations_remain_an_explicit_error(monkeypatch):
    calls = []

    def invalid(*_args, **_kwargs):
        calls.append(1)
        raise ValueError("No grounded citations")

    monkeypatch.setattr(risks, "generate_with_fallback", invalid)
    with pytest.raises(ValueError, match="No grounded citations"):
        risks.analyze_risks("PAGE 1\nДоговор", {})
    assert len(calls) == 2


def test_global_extraction_evidence_cannot_leak_into_another_risk_chunk(monkeypatch):
    prompts = []

    def capture(prompt, **_kwargs):
        prompts.append(prompt)
        return []

    monkeypatch.setattr(risks, "generate_with_fallback", capture)
    fields = {"parties": [{"name": "Альфа", "role": "Поставщик", "name_evidence": "ЦИТАТА ИЗ ДРУГОЙ ЧАСТИ"}],
              "term": {"evidence": "ДРУГОЕ УСЛОВИЕ"}}
    assert risks.analyze_risks("PAGE 8\nПодписи сторон.", fields) == []
    assert "Альфа" in prompts[0]
    assert "ЦИТАТА ИЗ ДРУГОЙ ЧАСТИ" not in prompts[0]
    assert "ДРУГОЕ УСЛОВИЕ" not in prompts[0]


def test_truncated_nonempty_analysis_is_not_presented_as_complete(monkeypatch):
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "length", "message": {"content": "Незавершённый ответ"}}]
    }))
    monkeypatch.setattr(summary, "api_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(summary, "resolve_model", lambda *_args: "synthetic-model")
    with pytest.raises(RuntimeError, match="лимит токенов"):
        summary.generate_chat("Договор", model="synthetic-model", max_tokens=2, provider="deepcode")
