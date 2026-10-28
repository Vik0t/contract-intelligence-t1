import json
import sys
from types import SimpleNamespace

import pytest

from backend.config import Settings
from backend.extraction import ExtractionService
from src.extraction import chat_pipeline, model_loading, pipeline, runtime
from src.extraction.provenance import model_identity, processing_provenance
from src.extraction.validation import validate_model_result


@pytest.fixture(autouse=True)
def isolated_model_cache(monkeypatch):
    model_loading.load_model.cache_clear()
    model_loading._loaded_model_provenance.clear()
    for key in ('CONTRACT_MODEL_REVISION', 'CONTRACT_MLX_MODEL_ID', 'CONTRACT_MLX_MODEL_REVISION'):
        monkeypatch.delenv(key, raising=False)
    yield
    model_loading.load_model.cache_clear()
    model_loading._loaded_model_provenance.clear()


def fake_transformers(monkeypatch, commit):
    calls = []
    model = SimpleNamespace(config=SimpleNamespace(_commit_hash=commit))
    model.eval = lambda: model
    monkeypatch.setattr(model_loading, 'use_mlx', lambda: False)
    monkeypatch.setattr(model_loading.torch.cuda, 'is_available', lambda: False)
    monkeypatch.setattr(model_loading.torch.backends.mps, 'is_available', lambda: False)
    monkeypatch.setattr(model_loading, 'MODEL_ID', 'example/loaded-transformers')
    monkeypatch.setattr(model_loading.AutoProcessor, 'from_pretrained', lambda *a, **kw: object())

    def load(model_id, **kwargs):
        calls.append((model_id, kwargs))
        return model

    monkeypatch.setattr(model_loading.AutoModelForMultimodalLM, 'from_pretrained', load)
    return calls


def test_api_does_not_inherit_local_revision_and_captures_actual_call(monkeypatch):
    monkeypatch.setenv('EXTRACTION_API_MODEL', 'provider/requested-model')
    monkeypatch.setenv('EXTRACTION_API_PROVIDER', 'test-provider')
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'unrelated-local-revision')
    monkeypatch.setenv('EXTRACTION_API_REPAIR_ENABLED', 'false')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-secret-not-for-provenance')
    calls = []

    def generate(_prompt, **kwargs):
        calls.append(kwargs)
        monkeypatch.setenv('EXTRACTION_API_MODEL', 'provider/later-model')
        monkeypatch.setenv('EXTRACTION_API_PROVIDER', 'later-provider')
        return json.dumps({'contract_number': {'value': '42', 'evidence': 'Договор № 42'}})

    monkeypatch.setattr(chat_pipeline, 'generate_chat', generate)
    fields, _ = chat_pipeline.extract_fields_with_api('PAGE 1\nДоговор № 42')
    saved = processing_provenance('api', fields['_provenance'])
    assert saved['model'] == calls[0]['model'] == 'provider/requested-model'
    assert saved['provider'] == calls[0]['provider'] == 'test-provider'
    assert saved['model_revision'] is None
    assert saved['model_revision_source'] == 'unknown'
    assert 'unrelated-local-revision' not in json.dumps(saved)
    assert 'synthetic-secret-not-for-provenance' not in json.dumps(saved)


def test_reported_revision_is_preserved_without_guessing_from_environment(monkeypatch):
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'wrong-revision')
    captured = model_identity('provider/actual-model', 'api', 'provider-revision', revision_source='provider')
    assert processing_provenance('api', captured)['model_revision'] == 'provider-revision'
    assert processing_provenance('local')['model'] is None
    assert processing_provenance('api')['model_revision'] is None
    assert processing_provenance('rules')['model_revision_source'] == 'not_applicable'


def test_transformers_keeps_loaded_identity_when_environment_changes(monkeypatch):
    calls = fake_transformers(monkeypatch, 'a' * 40)
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'release-alias')
    first = model_loading.load_model()
    monkeypatch.setattr(model_loading, 'MODEL_ID', 'example/later-model')
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'b' * 40)
    assert model_loading.load_model() is first
    identity = model_loading.get_loaded_model_provenance()
    assert identity['model'] == calls[0][0] == 'example/loaded-transformers'
    assert identity['model_revision'] == 'a' * 40
    assert identity['model_requested_revision'] == calls[0][1]['revision'] == 'release-alias'
    identity['model'] = 'caller-edit'
    assert model_loading.get_loaded_model_provenance()['model'] == 'example/loaded-transformers'


def test_unresolved_transformers_alias_is_not_reported_as_an_actual_commit(monkeypatch):
    fake_transformers(monkeypatch, None)
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'moving-alias')
    model_loading.load_model()
    identity = model_loading.get_loaded_model_provenance()
    assert identity['model_requested_revision'] == 'moving-alias'
    assert identity['model_revision'] is None
    assert identity['model_revision_source'] == 'unknown'


@pytest.mark.parametrize('configured_id', [None, 'example/custom-mlx'])
def test_mlx_records_the_loaded_snapshot_not_the_transformers_model(monkeypatch, tmp_path, configured_id):
    snapshot = tmp_path / 'snapshots' / ('c' * 40)
    snapshot.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(model_loading, 'use_mlx', lambda: True)
    monkeypatch.setenv('CONTRACT_MODEL_ID', 'wrong/base-model')
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'wrong-base-revision')
    monkeypatch.setenv('CONTRACT_MLX_MODEL_REVISION', 'mlx-release')
    if configured_id:
        monkeypatch.setenv('CONTRACT_MLX_MODEL_ID', configured_id)
    expected_id = configured_id or 'numind/NuExtract3-mlx-8bits'

    def download(model_id, **kwargs):
        assert model_id == expected_id
        assert kwargs['revision'] == 'mlx-release'
        assert 'model*.safetensors' in kwargs['allow_patterns']
        return str(snapshot)

    monkeypatch.setattr('huggingface_hub.snapshot_download', download)
    monkeypatch.setitem(sys.modules, 'mlx_lm', SimpleNamespace(load=lambda path: (calls.append(path) or object(), object())))
    model_loading.load_model()
    identity = model_loading.get_loaded_model_provenance()
    assert calls == [str(snapshot.resolve())]
    assert identity['model'] == expected_id
    assert identity['model_runtime'] == 'mlx'
    assert identity['model_revision'] == 'c' * 40
    assert identity['model_revision_source'] == 'snapshot'


def test_mlx_local_directory_does_not_invent_a_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(model_loading, 'use_mlx', lambda: True)
    monkeypatch.setenv('CONTRACT_MLX_MODEL_ID', str(tmp_path))
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'wrong-base-revision')
    monkeypatch.setattr('huggingface_hub.snapshot_download', lambda *a, **kw: pytest.fail('Local model attempted a download'))
    monkeypatch.setitem(sys.modules, 'mlx_lm', SimpleNamespace(load=lambda path: (object(), object())))
    model_loading.load_model()
    assert model_loading.get_loaded_model_provenance()['model_revision'] is None


def test_local_pipeline_retains_identity_after_service_unloads_model(monkeypatch):
    fake_transformers(monkeypatch, 'd' * 40)
    monkeypatch.setattr(runtime, 'release_device_memory', lambda: None)
    monkeypatch.setenv('ML_KEEP_MODELS_LOADED', 'false')

    def extract(text, _document=None, **kwargs):
        model_loading.load_model()
        return validate_model_result({'contract_number': {'value': '42', 'evidence': 'Договор № 42'}}, text)

    monkeypatch.setattr(pipeline, 'extract_fields_from_text', extract)
    fields, _ = ExtractionService(Settings(_env_file=None, extraction_backend='local')).extract(text='PAGE 1\nДоговор № 42')
    assert model_loading.get_loaded_model_provenance() == {}
    saved = processing_provenance('local', fields['_provenance'])
    assert saved['model'] == 'example/loaded-transformers'
    assert saved['model_revision'] == 'd' * 40
    assert saved['parameters']['max_new_tokens'] == 4096
    assert saved['messages'][0][0]['content'][0]['text'] == 'PAGE 1\nДоговор № 42'
