from copy import deepcopy
from hashlib import sha256
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from scripts.package_api_release import validate_acceptance_report
from scripts import package_api_release


IMAGES = [{'Id': 'backend-id'}, {'Id': 'frontend-id'}, {'Id': 'database-id'}]


def valid_report():
    cases = {
        'register.success': 200, 'login.success': 200, 'upload.success': 202,
        'registry.success': 200, 'card.success': 200, 'delete.success': 200,
        'health.ready': 200, 'health.unready': 503, 'upload.nginx_413': 413,
        'register.duplicate': 400, 'login.invalid': 401, 'card.forbidden': 403, 'card.missing': 404,
    }
    return {
        'kind': 'A-10', 'passed': True, 'commit': 'tested-commit',
        'runtime_source_sha256': 'tested-sources',
        'images': dict(zip(('backend', 'frontend', 'db'), (image['Id'] for image in IMAGES))),
        'checks': [{'case': name, 'status_code': code, 'passed': True} for name, code in cases.items()],
        'extraction': {'backend': 'local', 'model': 'synthetic/extractor', 'revision': 'synthetic-revision',
                       'terminal_status': 'extracted', 'quantization': 'bf16',
                       'verified_provenance': {'backend': 'local', 'model': 'synthetic/extractor',
                                               'model_revision': 'synthetic-revision', 'model_runtime': 'transformers'}},
    }


def test_release_accepts_exactly_the_tested_images_and_source():
    validate_acceptance_report(valid_report(), 'tested-commit', IMAGES, 'tested-sources')


@pytest.mark.parametrize('mismatch', ['commit', 'runtime_hash', 'image', 'failed_check', 'no_proxy_413', 'failed_report'])
def test_release_rejects_stale_or_incomplete_acceptance_evidence(mismatch):
    report = deepcopy(valid_report())
    if mismatch == 'commit':
        report['commit'] = 'different-commit'
    elif mismatch == 'runtime_hash':
        report['runtime_source_sha256'] = 'different-source'
    elif mismatch == 'image':
        report['images']['frontend'] = 'untested-image'
    elif mismatch == 'failed_check':
        report['checks'][0]['passed'] = False
    elif mismatch == 'no_proxy_413':
        report['checks'] = [case for case in report['checks'] if case['case'] != 'upload.nginx_413']
    else:
        report['passed'] = False
    with pytest.raises(ValueError):
        validate_acceptance_report(report, 'tested-commit', IMAGES, 'tested-sources')


@pytest.mark.parametrize('backend,model,runtime', [
    ('local', 'synthetic/local-model', 'transformers'),
    ('api', 'synthetic-api-model', 'api'),
    ('huggingface-space', 'synthetic/space', 'gradio'),
    ('rules', None, 'rules'),
])
def test_release_accepts_the_inference_selected_for_the_report(backend, model, runtime):
    report = valid_report()
    report['extraction'].update(backend=backend, model=model, revision=None)
    report['extraction']['verified_provenance'] = {'backend': backend, 'model': model, 'model_runtime': runtime}
    validate_acceptance_report(report, 'tested-commit', IMAGES, 'tested-sources')


def test_review_build_requires_the_exact_source_tree():
    report = valid_report()
    report.update(commit=None, source_tree='reviewed-tree')
    validate_acceptance_report(report, None, IMAGES, 'tested-sources', 'reviewed-tree')
    with pytest.raises(ValueError, match='source tree'):
        validate_acceptance_report(report, None, IMAGES, 'tested-sources', 'different-tree')
    with pytest.raises(ValueError, match='explicit source tree'):
        validate_acceptance_report(report, None, IMAGES, 'tested-sources')


def test_streamed_bundle_preserves_image_bytes_and_checksums(monkeypatch, tmp_path):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'README.txt').write_text('Synthetic deployment instructions')
    script = bundle / 'load-images.sh'
    script.write_text('#!/bin/sh\nexit 0\n')
    script.chmod(0o755)
    payload = b'synthetic-docker-export' * 1024
    original_popen = package_api_release.subprocess.Popen
    calls = []

    def popen(command, **kwargs):
        if command[:3] == ['docker', 'image', 'save']:
            calls.append(command)
            return SimpleNamespace(stdout=io.BytesIO(payload), wait=lambda: 0)
        return original_popen(command, **kwargs)

    monkeypatch.setattr(package_api_release.subprocess, 'Popen', popen)
    archive_path = tmp_path / 'review.tar.gz'
    package_api_release.write_bundle(archive_path, bundle, ['synthetic:1.0.0'])
    assert len(calls) == 2
    assert not (bundle / 'images.tar').exists()
    with tarfile.open(archive_path) as archive:
        assert archive.extractfile('bundle/images.tar').read() == payload
        assert archive.getmember('bundle/load-images.sh').mode & 0o111
        checksums = archive.extractfile('bundle/SHA256SUMS').read().decode()
        for line in checksums.splitlines():
            expected, name = line.split('  ', 1)
            assert sha256(archive.extractfile('bundle/' + name).read()).hexdigest() == expected


@pytest.mark.parametrize('backend,gpu', [('local', True), ('api', False)])
def test_package_manifest_records_the_supplied_inference_configuration(monkeypatch, tmp_path, backend, gpu):
    repo = tmp_path / 'repo'
    (repo / 'scripts').mkdir(parents=True)
    templates = repo / 'deploy/server'
    templates.mkdir(parents=True)
    (templates / 'README.txt').write_text('Configured deployment')
    (templates / 'compose.yaml').write_text('services: {}\n')
    monkeypatch.setattr(package_api_release, '__file__', str(repo / 'scripts/package_api_release.py'))
    identity = {'commit': 'tested-commit', 'base_commit': 'tested-commit', 'tree': 'tested-tree',
                'revision_label': 'tested-commit', 'status': 'committed'}
    monkeypatch.setattr(package_api_release, 'source_identity', lambda repo, review=False: identity)
    images = [dict(image, Os='linux', Architecture='amd64', Size=1,
                   Config={'Labels': {'org.opencontainers.image.revision': 'tested-commit'}}) for image in IMAGES]
    report = valid_report()
    report.update(source_tree='tested-tree', runtime_source_sha256=sha256(b'').hexdigest(),
                  extraction={'backend': backend, 'model': 'custom/selected-model', 'revision': 'configured-revision'},
                  inference={'summary': {'backend': 'api', 'model': 'custom-summary'}},
                  deployment={'gpu_required': gpu})
    report_path = tmp_path / 'report.json'
    report_path.write_text(json.dumps(report))
    output = tmp_path / 'dist'
    monkeypatch.setattr('sys.argv', ['package', '--output', str(output), '--validation-report', str(report_path)])
    payload = b'synthetic-docker-image-bytes'
    original_run = package_api_release.subprocess.run
    original_popen = package_api_release.subprocess.Popen

    def run(command, **kwargs):
        if command[:2] == ['git', 'archive']:
            with tarfile.open(command[command.index('-o') + 1], 'w:gz'):
                pass
            return SimpleNamespace(returncode=0)
        if command[:3] == ['docker', 'image', 'load']:
            assert kwargs['stdin'].read() == payload
            return SimpleNamespace(returncode=0)
        return original_run(command, **kwargs)

    def popen(command, **kwargs):
        if command[:3] == ['docker', 'image', 'save']:
            return SimpleNamespace(stdout=io.BytesIO(payload), wait=lambda: 0)
        return original_popen(command, **kwargs)

    monkeypatch.setattr(package_api_release.subprocess, 'run', run)
    monkeypatch.setattr(package_api_release.subprocess, 'Popen', popen)
    monkeypatch.setattr(package_api_release.subprocess, 'check_output', lambda command: json.dumps(images).encode())
    package_api_release.main()
    with tarfile.open(output / 'contract-intelligence-1.0.0-linux-amd64.tar.gz') as archive:
        manifest = json.load(archive.extractfile('bundle/build-manifest.json'))
    assert manifest['extraction'] == report['extraction']
    assert manifest['inference'] == report['inference']
    assert manifest['gpu_required'] is gpu
