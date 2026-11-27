from hashlib import sha256
import io
import tarfile
from types import SimpleNamespace

from scripts import package_api_release


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
