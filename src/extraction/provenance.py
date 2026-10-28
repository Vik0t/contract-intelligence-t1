"""Persist enough information to reproduce an extraction without saving secrets."""
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

from src.extraction.reliability import RULES_VERSION


@lru_cache(maxsize=1)
def runtime_versions():
    dependencies = {}
    for name in ('pydantic', 'transformers', 'torch', 'mlx-lm', 'python-docx', 'PyMuPDF', 'fastapi', 'sqlalchemy'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            pass
    root = Path(__file__).parent
    sources = [*root.glob('*.py'), *(root.parent / name for name in ('parsing.py', 'pdf_parser.py', 'document_ir.py', 'ocr.py')),
               root.parents[1] / 'backend' / 'extraction.py']
    digest = sha256(b''.join(path.name.encode() + b'\0' + path.read_bytes() for path in sorted(sources))).hexdigest()
    return {'dependencies': dependencies, 'rules_sha256': digest}


def model_identity(model, runtime, revision=None, *, revision_source=None, requested_revision=None):
    """Describe the loaded model or the ID actually passed to a provider."""
    return {'model': model, 'model_runtime': runtime, 'model_revision': revision,
            'model_revision_source': revision_source or ('runtime' if revision else 'unknown'),
            'model_requested_revision': requested_revision}


def processing_provenance(backend, captured=None, seconds=None):
    # Configuration may have changed since loading/generation. Identity and
    # parameters must be captured by that operation, never guessed at save time.
    identity = model_identity(None, backend, revision_source='not_applicable' if backend == 'rules' else 'unknown')
    return {**runtime_versions(), 'backend': backend, **identity,
            'instructions': None, 'template': None, 'parameters': {},
            **(captured or {}), 'rules_version': RULES_VERSION,
            'processed_at': datetime.now(timezone.utc).isoformat(), 'extraction_seconds': seconds}
