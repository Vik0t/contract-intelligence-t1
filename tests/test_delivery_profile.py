import json
from hashlib import sha256

import httpx
import pymupdf
import pytest

from backend.config import Settings
from backend.delivery_profile import PROFILE, PROFILE_ID, profile_digest, validate_delivery_profile
from backend import document_processing
from scripts.acceptance_http import HttpAcceptanceRunner
from scripts.evaluate_acceptance import evaluate


@pytest.fixture(autouse=True)
def profile_environment(monkeypatch):
    for key, value in {'ML_ALLOW_EXTERNAL': 'false', 'SUMMARY_BACKEND': 'local', 'RISK_BACKEND': 'local'}.items():
        monkeypatch.setenv(key, value)


def pinned_settings(**overrides):
    values = dict(delivery_profile=PROFILE_ID, extraction_backend='rules',
        database_url='postgresql://user:secret@db/contracts', docx_use_rendered_pages=False,
        allow_ocr_uploads=False, auto_extract_uploads=True, max_upload_size_mb=50, max_pdf_pages=200)
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize('change', [dict(extraction_backend='api'), dict(docx_use_rendered_pages=True),
    dict(allow_ocr_uploads=True), dict(auto_extract_uploads=False), dict(database_url='sqlite:///test.db')])
def test_pinned_profile_rejects_incompatible_runtime(change):
    with pytest.raises(RuntimeError, match='configuration mismatch'):
        validate_delivery_profile(pinned_settings(**change))


@pytest.mark.parametrize('enabled', ['true', '1', ' YES '])
def test_profile_excludes_secrets_and_rejects_external_inference(monkeypatch, enabled):
    profile = validate_delivery_profile(pinned_settings())
    assert profile == {'profile': PROFILE, 'profile_sha256': profile_digest(PROFILE)}
    assert 'secret' not in json.dumps(profile)
    monkeypatch.setenv('ML_ALLOW_EXTERNAL', enabled)
    with pytest.raises(RuntimeError, match='external_inference'):
        validate_delivery_profile(pinned_settings())


def test_disabled_ocr_is_not_constructed_even_for_blank_pdf_pages(tmp_path, monkeypatch):
    path = tmp_path / 'digital-plus-blank.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), 'Agreement with a digital text layer, number 42')
        pdf.new_page()
        pdf.save(path)
    monkeypatch.setattr(document_processing, 'TesseractOCRBackend', lambda: pytest.fail('OCR must be disabled'))
    text, document = document_processing.parse_for_extraction(path, pinned_settings())
    assert 'number 42' in text
    assert len(document.pages) == 2
    assert not any(block.source == 'ocr' for page in document.pages for block in page.blocks)


def test_http_evaluator_rejects_other_profile_before_upload():
    requests = []
    def handle(request):
        requests.append(request.method)
        return httpx.Response(200, json={'profile': {**PROFILE, 'docx_parser': 'rendered-pdf'},
                                         'profile_sha256': profile_digest(PROFILE)})
    client = httpx.Client(transport=httpx.MockTransport(handle), base_url='http://test/')
    with pytest.raises(ValueError, match='pinned'):
        HttpAcceptanceRunner('http://test', 'synthetic-token', client=client)
    assert requests == ['GET']


def test_manifest_requires_both_formats_before_any_upload(tmp_path):
    manifest = {'documents': [{'id': 'one', 'split': 'holdout', 'files': {}, 'sha256': {}}]}
    data = json.dumps(manifest).encode()
    (tmp_path / 'manifest.json').write_bytes(data)
    (tmp_path / 'manifest.sha256').write_text(sha256(data).hexdigest())
    with pytest.raises(ValueError, match='both PDF and DOCX'):
        evaluate(tmp_path, tmp_path / 'report.json', transport='http', base_url='http://test', token='synthetic-token')
    assert not (tmp_path / 'report.json').exists()


def test_evaluator_preserves_existing_evidence(tmp_path):
    report = tmp_path / 'report.json'
    report.write_text('original')
    with pytest.raises(FileExistsError):
        evaluate(tmp_path, report)
    assert report.read_text() == 'original'
