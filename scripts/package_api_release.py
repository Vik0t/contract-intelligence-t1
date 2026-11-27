"""Export configured deployment images, source identity and verification evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

def digest(path):
    result = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


class HashingReader:
    """Hash a streamed image export without storing an extra image copy."""

    def __init__(self, stream):
        self.stream = stream
        self.digest = sha256()

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.digest.update(chunk)
        return chunk


def write_bundle(archive_path, bundle, tags):
    command = ['docker', 'image', 'save', '--platform', 'linux/amd64', *tags]
    # Tar needs the nested archive's size. Count a first export; keep both passes off disk.
    counter = subprocess.Popen(command, stdout=subprocess.PIPE)
    image_size = 0
    while chunk := counter.stdout.read(8 * 1024 * 1024):
        image_size += len(chunk)
    counter.stdout.close()
    if counter.wait():
        raise RuntimeError('Image export failed')
    files = sorted(path for path in bundle.rglob('*') if path.is_file())
    checksums = ''.join(f'{digest(path)}  {path.relative_to(bundle)}\n' for path in files)
    with archive_path.open('wb') as destination:
        compressor = subprocess.Popen(['gzip', '-1'], stdin=subprocess.PIPE, stdout=destination)
        with tarfile.open(fileobj=compressor.stdin, mode='w|') as archive:
            for path in [bundle, *sorted(bundle.rglob('*'))]:
                archive.add(path, arcname='bundle' + ('/' + str(path.relative_to(bundle)) if path != bundle else ''), recursive=False)
            saved = subprocess.Popen(command, stdout=subprocess.PIPE)
            reader = HashingReader(saved.stdout)
            image = tarfile.TarInfo('bundle/images.tar')
            image.size = image_size
            image.mode = 0o600
            archive.addfile(image, reader)
            extra = saved.stdout.read(1)
            saved.stdout.close()
            if saved.wait() or extra:
                raise RuntimeError('Image export size changed while packaging')
            sums = bundle / 'SHA256SUMS'
            sums.write_text(checksums + f'{reader.digest.hexdigest()}  images.tar\n')
            archive.add(sums, arcname='bundle/SHA256SUMS')
        compressor.stdin.close()
        if compressor.wait():
            raise RuntimeError('Release compression failed')


def source_identity(repo, *, review=False):
    """Identify review sources by tree without creating commits or changing staging."""
    def git(*args, **kwargs):
        return subprocess.check_output(['git', *args], cwd=repo, text=True, **kwargs).strip()
    head = git('rev-parse', 'HEAD')
    if not review:
        if git('status', '--porcelain'):
            raise RuntimeError('Commit reviewed changes before packaging a release, or explicitly use --review')
        return {'commit': head, 'base_commit': head, 'tree': git('rev-parse', 'HEAD^{tree}'),
                'revision_label': head, 'status': 'committed'}
    with tempfile.TemporaryDirectory(prefix='contract-review-index-') as temporary:
        index = Path(temporary) / 'index'
        current = Path(git('rev-parse', '--git-path', 'index'))
        shutil.copy2(current if current.is_absolute() else repo / current, index)
        env = {**os.environ, 'GIT_INDEX_FILE': str(index)}
        git('add', '--all', '--', '.', env=env)
        tree = git('write-tree', env=env)
    return {'commit': None, 'base_commit': head, 'tree': tree,
            'revision_label': 'uncommitted:' + tree, 'status': 'review_uncommitted'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', default='1.0.0')
    parser.add_argument('--logs', type=Path)
    parser.add_argument('--validation-report', type=Path, required=True, help='Successful A-10 JSON for these exact source and image IDs')
    parser.add_argument('--review', action='store_true', help='Package an explicitly marked, uncommitted source snapshot for review')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    identity = source_identity(repo, review=args.review)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / 'bundle'
    bundle.mkdir()
    templates = repo / 'deploy/server'
    for source in templates.iterdir():
        if source.is_file() and source.name not in {'RELEASE_NOTES.md', 'live-validation-2026-11-20.json'}:
            shutil.copy2(source, bundle / source.name)
    assert not (bundle / '.env.server').exists()
    tags = [f'contract-intelligence-{name}:{args.tag}' for name in ('backend', 'frontend', 'db')]
    for name in ('compose.yaml', 'README.txt'):
        path = bundle / name
        path.write_text(path.read_text().replace(':1.0.0', ':' + args.tag))
    images = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *tags]))
    assert all(image['Os'] == 'linux' and image['Architecture'] == 'amd64' for image in images)
    if source_identity(repo, review=args.review) != identity:
        raise RuntimeError('Sources changed while preparing the package')
    if any(image['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != identity['revision_label'] for image in images[:2]):
        raise ValueError('Backend/frontend image revision does not match the source commit')
    paths = sorted(p for folder in ('backend', 'src', 'scripts') for p in (repo / folder).rglob('*.py'))
    runtime_hash = sha256(b''.join(str(p.relative_to(repo)).encode() + b'\0' + p.read_bytes() for p in paths)).hexdigest()
    report = json.loads(args.validation_report.read_text())
    shutil.copy2(args.validation_report, bundle / 'a10-validation.json')
    validation = {'openapi_a10': 'a10-validation.json', 'real_model': 'a10-validation.json',
                  'note': 'A-10 passed on these exact source and image IDs; inference configuration is recorded in the report.'}
    manifest = {
        'repository': 'https://github.com/Vik0t/contract-intelligence-t1', 'commit': identity['commit'],
        'source_tree': identity['tree'], 'base_commit': identity['base_commit'], 'delivery_status': identity['status'],
        'version': '1.0.0',
        'release_tag': args.tag, 'created_at': datetime.now(timezone.utc).isoformat(),
        'platform': 'linux/amd64', 'runtime_source_sha256': runtime_hash,
        'images': [{'tag': tag, 'id': item['Id'], 'size_bytes': item['Size'],
                    'repo_digests': item.get('RepoDigests', [])} for tag, item in zip(tags, images)],
        'extraction': report.get('extraction', {}),
        'inference': report.get('inference', {}),
        'gpu_required': report.get('deployment', {}).get('gpu_required'),
        'weights_included': False, 'secrets_included': False,
        'validation': validation,
    }
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    subprocess.run(['git', 'archive', '--format=tar.gz', '-o', str(bundle / 'source.tar.gz'), identity['tree']], cwd=repo, check=True)
    if args.logs:
        log_dir = bundle / 'logs'
        log_dir.mkdir()
        # Only these non-secret build/test logs are allowed into the release.
        for name in ('backend-tests.log', 'frontend-tests.log', 'build-backend.log', 'build-frontend.log'):
            source = args.logs / name
            if source.is_file():
                shutil.copy2(source, log_dir / name)
    archive_path = output / f'contract-intelligence-{args.tag}-linux-amd64.tar.gz'
    write_bundle(archive_path, bundle, tags)
    # Verify the actual bytes included in the archive with Docker, using a pipe.
    exported = subprocess.Popen(['tar', '-xOzf', str(archive_path), 'bundle/images.tar'], stdout=subprocess.PIPE)
    result = subprocess.run(['docker', 'image', 'load'], stdin=exported.stdout)
    exported.stdout.close()
    if exported.wait() or result.returncode:
        raise RuntimeError('Packaged images could not be loaded')
    loaded = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *tags]))
    if [image['Id'] for image in loaded] != [image['Id'] for image in images]:
        raise ValueError('Save/load changed image IDs; repeat A-10 on the loaded images before packaging')
    archive_path.with_name(archive_path.name + '.sha256').write_text(f'{digest(archive_path)}  {archive_path.name}\n')
    print(json.dumps({'archive': str(archive_path), 'commit': identity['commit'], 'source_tree': identity['tree'], 'images': tags}))


if __name__ == '__main__':
    main()
