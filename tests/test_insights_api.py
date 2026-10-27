import json
import os
from pathlib import Path
import subprocess
import sys
import httpx
import pytest

from src.extraction import risks, summary


def test_local_analysis_imports_without_api_credentials():
    """Importing the backend must not initialize a hosted client or require a key."""
    env = {key: value for key, value in os.environ.items() if key not in {"OPENAI_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN"}}
    env.update(PYTHON_DOTENV_DISABLED="1", SUMMARY_BACKEND="local", ML_ALLOW_EXTERNAL="false")
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; from src.extraction import summary, risk_review; assert summary.summary_backend() == 'local'; runpy.run_path('deepseek_test.py')"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def explicitly_enable_mocked_hosted_analysis(monkeypatch):
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "true")
    monkeypatch.setenv("ML_HF_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("SUMMARY_BACKEND", "api")
    monkeypatch.setenv("RISK_BACKEND", "api")


def test_deepcode_provider_uses_configured_openai_compatible_endpoint(monkeypatch):
    called = {}

    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "Краткая сводка"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            called["timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def close(self):
            pass

        def post(self, url, **kwargs):
            called["url"] = url
            called["headers"] = kwargs["headers"]
            called["json"] = kwargs["json"]
            return FakeResponse()

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("SUMMARY_PROVIDER", "deepcode")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://internal.example/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(summary.httpx, "Client", FakeClient)

    assert summary.generate_chat("Текст", model="test-model", max_tokens=20) == "Краткая сводка"
    assert called["url"] == "https://internal.example/api/v1/chat/completions"
    assert called["headers"]["Authorization"] == "Bearer test-key"
    assert called["json"]["model"] == "test-model"


def test_risks_require_verbatim_evidence(monkeypatch):
    payload = [
        {"title": "Автопродление", "body": "Проверьте срок отказа.", "evidence": "Договор продлевается автоматически", "page": 2},
        {"title": "Выдуманный риск", "body": "Без цитаты.", "evidence": "Такого текста нет", "page": 1},
    ]
    monkeypatch.setattr(risks, "generate_with_fallback", lambda *_args, **kwargs: kwargs["parse"](json.dumps(payload, ensure_ascii=False)))
    result = risks.analyze_risks("PAGE 2\n\nДоговор продлевается автоматически.", {})
    assert len(result) == 1
    assert result[0]["page"] == 2


def test_summary_uses_hugging_face_after_deepcode_timeout(monkeypatch):
    calls = []

    def fake_generate(prompt, *, model, provider, **_kwargs):
        calls.append((provider, model))
        if provider == "deepcode":
            raise httpx.ConnectTimeout("timeout")
        return "Сводка через резервный сервис."

    monkeypatch.setenv("SUMMARY_PROVIDER", "deepcode")
    monkeypatch.setenv("SUMMARY_FALLBACK_MODEL_NAME", "hf-fallback-model")
    monkeypatch.setattr(summary, "generate_chat", fake_generate)

    assert summary.summarize_document("Текст договора", {}) == "Сводка через резервный сервис."
    assert calls == [("deepcode", summary.SUMMARY_MODEL_NAME), ("hf", "hf-fallback-model")]


def test_risks_retry_hugging_face_when_primary_reply_is_not_json(monkeypatch):
    calls = []
    valid = [{"title": "Продление", "body": "Проверьте срок.", "evidence": "Договор продлевается", "page": 1}]

    def fake_generate(prompt, *, model, provider, **_kwargs):
        calls.append((provider, model))
        return "не JSON" if provider == "deepcode" else json.dumps(valid, ensure_ascii=False)

    monkeypatch.setenv("RISK_PROVIDER", "deepcode")
    monkeypatch.setenv("RISK_FALLBACK_MODEL_NAME", "hf-risk-model")
    monkeypatch.setattr(summary, "generate_chat", fake_generate)

    result = risks.analyze_risks("PAGE 1\n\nДоговор продлевается", {})
    assert result[0]["title"] == "Продление"
    assert [provider for provider, _model in calls] == ["deepcode", "hf"]
    assert calls[1][1] == "hf-risk-model"


def test_no_fallback_loop_when_hugging_face_is_primary(monkeypatch):
    calls = []

    def unavailable(*_args, **kwargs):
        calls.append(kwargs["provider"])
        raise RuntimeError("HF unavailable")

    monkeypatch.setattr(summary, "generate_chat", unavailable)
    with pytest.raises(RuntimeError, match="HF unavailable"):
        summary.generate_with_fallback("Текст", model="hf-model", max_tokens=10, provider="hf")
    assert calls == ["hf"]
