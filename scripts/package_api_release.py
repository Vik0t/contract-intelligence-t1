"""Export the three API deployment images with configuration and provenance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def digest(path):
    result = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', default='deploy-2026-11-20-api')
    parser.add_argument('--logs', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / 'bundle'
    bundle.mkdir()
    templates = repo / 'deploy/api'
    for source in templates.iterdir():
        if source.is_file() and source.name != 'RELEASE_NOTES.md':
            shutil.copy2(source, bundle / source.name)
    assert not (bundle / '.env.server').exists()
    tags = [f'contract-intelligence-{name}:{args.tag}' for name in ('backend', 'frontend', 'db')]
    compose = (bundle / 'compose.yaml').read_text().replace('deploy-2026-11-20-api', args.tag)
    (bundle / 'compose.yaml').write_text(compose)
    images = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *tags]))
    assert all(image['Os'] == 'linux' and image['Architecture'] == 'amd64' for image in images)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    paths = sorted(p for folder in ('backend', 'src', 'scripts') for p in (repo / folder).rglob('*.py'))
    runtime_hash = sha256(b''.join(str(p.relative_to(repo)).encode() + b'\0' + p.read_bytes() for p in paths)).hexdigest()
    manifest = {
        'repository': 'https://github.com/Vik0t/contract-intelligence-t1', 'commit': commit,
        'release_tag': args.tag, 'created_at': datetime.now(timezone.utc).isoformat(),
        'platform': 'linux/amd64', 'runtime_source_sha256': runtime_hash,
        'images': [{'tag': tag, 'id': item['Id'], 'size_bytes': item['Size'],
                    'repo_digests': item.get('RepoDigests', [])} for tag, item in zip(tags, images)],
        'api': {'provider': 'deepcode', 'base_url': 'https://deepcode.ci.nsu.ru/api/v1', 'model': 'qwen3.8-flash-next'},
        'gpu_required': False, 'secrets_included': False,
        'validation': {'real_api': 'live-validation-2026-11-20.json',
                       'note': 'Real API validation ran locally on synthetic PDF/DOCX/JPG. CI does not use the API key.'},
    }
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    subprocess.run(['git', 'archive', '--format=tar.gz', '-o', str(bundle / 'source.tar.gz'), 'HEAD'], cwd=repo, check=True)
    if args.logs:
        log_dir = bundle / 'logs'
        log_dir.mkdir()
        # Only these non-secret build/test logs are allowed into the release.
        for name in ('backend-tests.log', 'frontend-tests.log', 'build-backend.log', 'build-frontend.log'):
            source = args.logs / name
            if source.is_file():
                shutil.copy2(source, log_dir / name)
    subprocess.run(['docker', 'image', 'save', '--platform', 'linux/amd64', '-o', str(bundle / 'images.tar'), *tags], check=True)
    with tarfile.open(bundle / 'images.tar') as archive:
        saved = json.load(archive.extractfile('manifest.json'))
    assert set(tags) <= {tag for item in saved for tag in item.get('RepoTags', [])}
    subprocess.run(['docker', 'image', 'load', '-i', str(bundle / 'images.tar')], check=True)
    files = sorted(path for path in bundle.rglob('*') if path.is_file())
    (bundle / 'SHA256SUMS').write_text(''.join(f'{digest(path)}  {path.relative_to(bundle)}\n' for path in files))
    archive_path = output / f'contract-intelligence-{args.tag}-linux-amd64.tar.gz'
    with archive_path.open('wb') as destination:
        tar = subprocess.Popen(['tar', '-C', str(output), '-cf', '-', 'bundle'], stdout=subprocess.PIPE)
        compressed = subprocess.run(['gzip', '-1'], stdin=tar.stdout, stdout=destination)
        tar.stdout.close()
        tar_code = tar.wait()
        if compressed.returncode or tar_code:
            raise RuntimeError('Release compression failed')
    archive_path.with_name(archive_path.name + '.sha256').write_text(f'{digest(archive_path)}  {archive_path.name}\n')
    print(json.dumps({'archive': str(archive_path), 'commit': commit, 'images': tags}))


if __name__ == '__main__':
    main()
