import json
from itertools import product

import pytest

from scripts.check_runtime import model_specs, verify_weights
from scripts.serve import runtime_requirements


def test_missing_model_shard_is_detected_before_startup(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"layer": "model-00001.safetensors"}}))
    with pytest.raises(RuntimeError, match="неполные"):
        verify_weights(tmp_path)
    (tmp_path / "model-00001.safetensors").write_bytes(b"synthetic-test-shard")
    verify_weights(tmp_path)


def configure_stages(monkeypatch, extraction, summary, risk):
    stages = (extraction, summary, risk)
    for key, value in {
        'EXTRACTION_BACKEND': extraction, 'SUMMARY_BACKEND': summary, 'RISK_BACKEND': risk,
        'ML_ALLOW_EXTERNAL': 'true',
        'CONTRACT_MODEL_ID': 'synthetic/extractor', 'CONTRACT_MODEL_REVISION': 'extractor-revision',
        'SUMMARY_LOCAL_MODEL_NAME': 'synthetic/insights', 'SUMMARY_LOCAL_MODEL_REVISION': 'insights-revision',
    }.items():
        monkeypatch.setenv(key, value)
    for key in ('OPENAI_BASE_URL', 'OPENAI_API_KEY', 'EXTRACTION_API_MODEL', 'SUMMARY_MODEL_NAME', 'RISK_MODEL_NAME'):
        monkeypatch.delenv(key, raising=False)
    if 'api' in stages:
        monkeypatch.setenv('OPENAI_BASE_URL', 'https://synthetic.invalid/v1')
        monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
    for backend, key in zip(stages, ('EXTRACTION_API_MODEL', 'SUMMARY_MODEL_NAME', 'RISK_MODEL_NAME')):
        if backend == 'api':
            monkeypatch.setenv(key, 'synthetic-api-model')


@pytest.mark.parametrize('stages', list(product(('local', 'api'), repeat=3)))
def test_startup_honors_independent_environment_backends(monkeypatch, stages):
    configure_stages(monkeypatch, *stages)
    expected = []
    if stages[0] == 'local':
        expected.append(('synthetic/extractor', 'extractor-revision'))
    if 'local' in stages[1:]:
        expected.append(('synthetic/insights', 'insights-revision'))
    assert model_specs() == expected
    assert runtime_requirements() == {'require_gpu': bool(expected), 'require_models': bool(expected)}


@pytest.mark.parametrize('insights', [('local', 'local'), ('api', 'api')])
def test_hosted_extraction_does_not_require_unused_extraction_api_credentials(monkeypatch, insights):
    configure_stages(monkeypatch, 'huggingface-space', *insights)
    expected = [('synthetic/insights', 'insights-revision')] if insights[0] == 'local' else []
    assert model_specs() == expected
    assert runtime_requirements() == {'require_gpu': bool(expected), 'require_models': bool(expected)}


@pytest.mark.parametrize('stages', [('local', 'api', 'local'), ('api', 'api', 'api')])
def test_hardware_preflight_does_not_impose_a_specific_api_provider(monkeypatch, stages):
    configure_stages(monkeypatch, *stages)
    monkeypatch.delenv('OPENAI_BASE_URL')
    monkeypatch.delenv('OPENAI_API_KEY')
    monkeypatch.setenv('HF_TOKEN', 'synthetic-provider-token')
    local = 'local' in stages
    assert runtime_requirements() == {'require_gpu': local, 'require_models': local}


@pytest.mark.parametrize('backend', ['api', 'huggingface-space'])
def test_remote_extraction_requires_external_permission(monkeypatch, backend):
    configure_stages(monkeypatch, backend, 'local', 'local')
    monkeypatch.setenv('ML_ALLOW_EXTERNAL', 'false')
    with pytest.raises(RuntimeError, match='ML_ALLOW_EXTERNAL=true'):
        runtime_requirements()


def test_rules_profile_does_not_load_unused_local_models(monkeypatch):
    configure_stages(monkeypatch, 'rules', 'local', 'local')
    monkeypatch.setenv('ML_ALLOW_EXTERNAL', 'false')
    assert runtime_requirements() == {'require_gpu': False, 'require_models': False}
    assert model_specs() == []
