import json
from itertools import product
from types import SimpleNamespace

import pytest

from scripts.check_runtime import model_specs, verify_cuda, verify_weights
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


def fake_cuda_runtime(ones):
    return SimpleNamespace(ones=ones, cuda=SimpleNamespace(
        get_device_capability=lambda: (8, 9), get_arch_list=lambda: ['sm_86'],
        get_device_name=lambda: 'Synthetic CUDA GPU',
        get_device_properties=lambda _: SimpleNamespace(total_memory=12 * 2**30),
    ))


def test_cuda_probe_accepts_a_compatible_minor_architecture():
    class Tensor:
        def __matmul__(self, other):
            return self
        def sum(self):
            return self
        def item(self):
            return 8.0
    gpu = verify_cuda(fake_cuda_runtime(lambda *a, **kw: Tensor()))
    assert gpu['architecture'] == 'sm_89'
    assert gpu['vram_gib'] == 12


def test_cuda_probe_rejects_a_real_kernel_failure():
    def unavailable(*args, **kwargs):
        raise RuntimeError('no kernel image is available')
    with pytest.raises(RuntimeError, match='CUDA-операция'):
        verify_cuda(fake_cuda_runtime(unavailable))
