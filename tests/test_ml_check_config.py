import json
import os
from types import SimpleNamespace

import pytest

import backend.extraction
from scripts import ml_check


@pytest.mark.parametrize('stages,overrides,expected,permission', [
    (('local', 'api', 'local'), [], ('local', 'api', 'local'), 'true'),
    (('api', 'local', 'api'), [], ('api', 'local', 'api'), 'false'),
    (('local', 'api', 'api'), ['--summary-backend', 'local'], ('local', 'local', 'api'), 'true'),
    (('local', 'local', 'api'), ['--backend', 'api'], ('api', 'local', 'api'), 'true'),
])
def test_ml_check_uses_environment_and_overrides_only_explicit_stages(monkeypatch, tmp_path, stages, overrides, expected, permission):
    keys = ('EXTRACTION_BACKEND', 'SUMMARY_BACKEND', 'RISK_BACKEND')
    for name, value in zip(keys, stages):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('ML_ALLOW_EXTERNAL', permission)
    settings_seen = []
    monkeypatch.setattr(backend.extraction, 'ExtractionService',
                        lambda settings: settings_seen.append(settings.extraction_backend) or SimpleNamespace())
    monkeypatch.setattr(ml_check, 'fixtures', lambda directory: {})
    output = tmp_path / 'report.json'
    monkeypatch.setattr('sys.argv', ['ml_check', '--parsing-only', '--output', str(output), *overrides])
    with pytest.raises(SystemExit) as result:
        ml_check.main()
    assert result.value.code == 0
    report = json.loads(output.read_text())
    assert (report['backend'], report['summary_backend'], report['risk_backend']) == expected
    assert settings_seen == [expected[0]]
    assert os.environ['ML_ALLOW_EXTERNAL'] == permission
