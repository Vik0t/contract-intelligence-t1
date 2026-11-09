"""The portable deployment must work without any local-model dependencies."""

import os
from pathlib import Path
import subprocess
import sys


def test_rules_and_api_import_without_local_model_packages(tmp_path):
    code = '''
import importlib.abc
import sys

class NoLocalModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'torchvision', 'transformers', 'mlx', 'mlx_lm', 'bitsandbytes'}:
            raise AssertionError('Portable runtime imported ' + fullname)

sys.meta_path.insert(0, NoLocalModels())
from backend.app import app
from backend.config import Settings
from backend.extraction import ExtractionService
from src.extraction.json_output import parse_json_output
from src.extraction.recovery import recover_missing
service = ExtractionService(Settings(_env_file=None, extraction_backend='rules'))
fields, usage = service.extract(text='Договор поставки № 42 от 10.11.2026')
assert fields['contract_number']['value'] == '42'
assert parse_json_output('```json\\n{"ok": true}\\n```') == {'ok': True}
'''
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'test.db'),
           'DOCUMENT_STORAGE_DIR': str(tmp_path / 'uploads'), 'DELIVERY_PROFILE': 'custom',
           'EXTRACTION_BACKEND': 'rules', 'ML_ALLOW_EXTERNAL': 'false'}
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
