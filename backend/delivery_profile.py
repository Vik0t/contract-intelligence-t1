"""The versioned configuration of the four-attribute PMI delivery."""
from hashlib import sha256
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url

PROFILE_ID = 'pmi-rules-v1'
PROFILE = {
    'id': PROFILE_ID,
    'extraction_backend': 'rules',
    'docx_parser': 'native',
    'pdf_parser': 'digital-text',
    'ocr_uploads': False,
    'external_inference': False,
    'auto_extract_uploads': True,
    'summary_backend': 'local',
    'risk_backend': 'local',
    'database': 'postgresql',
    'accepted_formats': ['pdf', 'docx'],
    'max_upload_size_mb': 50,
    'max_pdf_pages': 200,
    'performance_scope_pages': 20,
    'processing_limit_seconds': 10,
}


def profile_digest(profile):
    return sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def runtime_profile(settings):
    """Report effective configuration without credentials, paths or tokens."""
    profile = {**PROFILE, 'id': settings.delivery_profile,
        'extraction_backend': settings.extraction_backend,
        'docx_parser': 'rendered-pdf' if settings.docx_use_rendered_pages else 'native',
        'pdf_parser': 'ocr-fallback' if settings.allow_ocr_uploads else 'digital-text',
        'ocr_uploads': settings.allow_ocr_uploads,
        'external_inference': os.getenv('ML_ALLOW_EXTERNAL', 'false').strip().lower() in {'true', '1', 'yes'},
        'auto_extract_uploads': settings.auto_extract_uploads,
        'summary_backend': os.getenv('SUMMARY_BACKEND', 'local'),
        'risk_backend': os.getenv('RISK_BACKEND', 'local'),
        'database': make_url(settings.database_url).get_backend_name(),
        'accepted_formats': ['pdf', 'docx'] if settings.delivery_profile == PROFILE_ID else ['pdf', 'docx', 'jpg', 'jpeg', 'png'],
        'max_upload_size_mb': settings.max_upload_size_mb, 'max_pdf_pages': settings.max_pdf_pages}
    if settings.delivery_profile != PROFILE_ID:
        profile['processing_limit_seconds'] = 10 if settings.extraction_backend == 'rules' else 45
    return {'profile': profile, 'profile_sha256': profile_digest(profile)}


def validate_delivery_profile(settings):
    actual = runtime_profile(settings)
    if settings.delivery_profile == PROFILE_ID:
        mismatches = [key for key, expected in PROFILE.items() if actual['profile'].get(key) != expected]
        if mismatches:
            raise RuntimeError(f'{PROFILE_ID}: configuration mismatch: {", ".join(mismatches)}')
    return actual


def runtime_source_sha256():
    root = Path(__file__).resolve().parents[1]
    paths = sorted(p for folder in ('backend', 'src', 'scripts') for p in (root / folder).rglob('*.py'))
    return sha256(b''.join(str(p.relative_to(root)).encode() + b'\0' + p.read_bytes() for p in paths)).hexdigest()
