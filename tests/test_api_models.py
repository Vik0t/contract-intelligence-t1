import httpx
import pytest

from src.extraction import api_models
from scripts import benchmark_models
from src.extraction import summary
import json


@pytest.fixture(autouse=True)
def clean_alias_cache(monkeypatch):
    monkeypatch.setattr(api_models, "_aliases", {})


def test_case_insensitive_request_uses_exact_server_model_id_and_caches_it():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"id": "qwen3.8-flash-next"}, {"id": "Qwen3.8-27B"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert api_models.resolve_model(client, "https://test.invalid/v1", "secret", "Qwen3.8-Flash-Next", required=True) == "qwen3.8-flash-next"
        assert api_models.resolve_model(client, "https://test.invalid/v1", "secret", "qwen3.8-flash-next") == "qwen3.8-flash-next"
    assert len(calls) == 1


def test_resolver_never_substitutes_a_different_model():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "Qwen3.8-27B"}]}))) as client:
        with pytest.raises(ValueError, match="отсутствует"):
            api_models.resolve_model(client, "https://test.invalid/v1", "secret", "qwen3.8-flash-next", required=True)


def test_provider_error_keeps_reason_but_removes_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-for-test")
    request = httpx.Request("POST", "https://test.invalid/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": "Model not found; private-key-for-test Bearer another-secret"}})
    with pytest.raises(httpx.HTTPStatusError) as error:
        response.raise_for_status()
    details = api_models.safe_error_details(error.value)
    assert details["http_status"] == 400
    assert "Model not found" in details["error_message"]
    assert "private-key-for-test" not in details["error_message"]
    assert "another-secret" not in details["error_message"]


def test_failed_preflight_saves_report_before_running_local_model(monkeypatch, tmp_path):
    import json
    import sys
    import backend.extraction

    monkeypatch.setattr(benchmark_models.os, "environ", benchmark_models.os.environ.copy())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://test.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    output = tmp_path / "failed.json"
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output", str(output)])

    def fail(_model):
        raise ValueError("Requested model is unavailable")

    monkeypatch.setattr(benchmark_models, "preflight_model", fail)
    monkeypatch.setattr(backend.extraction, "ExtractionService", lambda *_args: pytest.fail("Local model must not start"))
    with pytest.raises(SystemExit) as error:
        benchmark_models.main()
    assert error.value.code == 1
    report = json.loads(output.read_text())
    assert report["api_preflight"]["error_message"] == "Requested model is unavailable"
    assert report["records"] == []


def test_deepcode_uses_resolved_model_and_disables_qwen_thinking(monkeypatch):
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://qwen-test.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DEEPCODE_ENABLE_THINKING", "false")
    posted = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "qwen3.8-flash-next"}]})
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Готово"}}]})

    client_class = httpx.Client
    monkeypatch.setattr(summary, "api_client", lambda: client_class(transport=httpx.MockTransport(handler)))
    assert summary.generate_chat("Текст", model="Qwen3.8-Flash-Next", max_tokens=100, provider="deepcode") == "Готово"
    assert posted[0]["model"] == "qwen3.8-flash-next"
    assert posted[0]["chat_template_kwargs"] == {"enable_thinking": False}
