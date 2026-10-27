"""Restore the document archive and the separate complete annotation archive.

Existing documents and labels are never overwritten with different content.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

DATASET_ID = '1gL5bwq3yOXkTBZuZbQkUXkqCyhBQgg7U'
META_ID = '1aSvJMbpT9Umq2omGPZoRIPBtFmZN3lZz'


def install_archive(archive: Path, destination: Path, *, labels: bool):
    payloads = {}
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            path = Path(member.filename)
            if '__MACOSX' in path.parts or member.is_dir():
                continue
            name = path.name
            valid = re.fullmatch(r'\d+\.json', name) if labels else re.fullmatch(r'Договор_\d+\.(pdf|docx|png)|meta\.json', name, re.I)
            if not valid:
                continue
            data = source.read(member)
            if name in payloads and payloads[name] != data:
                raise ValueError(f'Duplicate conflicting archive member: {name}')
            if labels:
                doc = json.loads(data)
                number = int(Path(name).stem)
                if doc.get('document_id') not in (number, str(number), f'contract_{number:03d}') or 'gold' not in doc:
                    raise ValueError(f'Invalid structured label: {name}')
            payloads[name] = data
    if not payloads:
        raise ValueError('Archive contains no expected documents or numbered labels')
    # Validate every destination before writing, preserving any operator edits.
    for name, data in payloads.items():
        target = destination / name
        if target.exists() and target.read_bytes() != data:
            raise FileExistsError(f'{target} differs from the archive; preserve it and select another destination')
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        target = destination / name
        if not target.exists():
            target.write_bytes(data)
    return {'files': len(payloads), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}


def download(file_id, destination):
    import gdown
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and zipfile.is_zipfile(destination):
        return destination
    temporary = destination.with_suffix('.zip.part')
    result = gdown.download(id=file_id, output=str(temporary), quiet=False)
    if result is None or not zipfile.is_zipfile(temporary):
        raise RuntimeError('Google Drive did not return a ZIP. Check access to the source file; existing data was preserved.')
    temporary.replace(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels-only', action='store_true')
    parser.add_argument('--meta-dir', type=Path, default=Path('meta'))
    parser.add_argument('--dataset-dir', type=Path, default=Path('dataset'))
    parser.add_argument('--archive-dir', type=Path, default=Path('tmp/dataset-sources'))
    parser.add_argument('--meta-archive', type=Path, help='Use a previously downloaded meta.zip')
    parser.add_argument('--dataset-archive', type=Path, help='Use a previously downloaded dataset.zip')
    args = parser.parse_args()
    if not args.labels_only:
        archive = args.dataset_archive or download(DATASET_ID, args.archive_dir / 'dataset.zip')
        print('Documents:', install_archive(archive, args.dataset_dir, labels=False))
    archive = args.meta_archive or download(META_ID, args.archive_dir / 'meta.zip')
    print('Structured labels:', install_archive(archive, args.meta_dir, labels=True))
    print('Use --labels meta for benchmarks. dataset/meta.json is the older, incomplete format.')


if __name__ == '__main__':
    main()
