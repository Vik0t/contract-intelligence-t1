"""Apply five source-checked corrections to a separate copy of upstream labels.

Never edit the downloaded meta.zip or the raw numbered JSON files in place.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
from src.evaluation_labels import load_labels

# SHA-256 of the 50 original numbered JSON files (names + NUL + raw bytes).
UPSTREAM_HASH = '81362d906af75335fcf1e89d60ec05240b897a35123022555a2677cefa87dc56'
FIXES = [
    (9, ('gold','vat','normalized_value'), 0, None, 'status=not_found, raw_value=null, no evidence: 0 is not a declared VAT rate'),
    (24, ('gold','vat','normalized_value'), 0, None, 'status=not_found, raw_value=null, no evidence: 0 is not a declared VAT rate'),
    (27, ('gold','vat','normalized_value'), 0, None, 'status=not_found, raw_value=null, no evidence: 0 is not a declared VAT rate'),
    (47, ('gold','vat','mode'), 'included', 'not_applicable', 'Original PDF page 2 explicitly states without VAT and exemption; not zero-rated included VAT'),
    (1, ('gold','vat','evidence',0,'page'), 2, 1, 'Verbatim VAT passage is on original PDF page 1; original page 2 has no VAT clause'),
]


def reviewed_copy(source: Path, output: Path):
    labels, provenance = load_labels(source)
    if provenance['sha256'] != UPSTREAM_HASH:
        raise ValueError('These corrections target the verified upstream snapshot only; review a changed source independently')
    if output.exists():
        raise FileExistsError('Use a new reviewed-label directory')
    reviewed = deepcopy(labels)
    changes = []
    for id, path, before, after, reason in FIXES:
        current = reviewed[id]
        for key in path[:-1]:
            current = current[key]
        if current[path[-1]] != before:
            raise ValueError(f'Correction precondition failed for contract {id}')
        current[path[-1]] = after
        changes.append({'document_id': id, 'path': list(path), 'before': before, 'after': after, 'reason': reason})
    output.mkdir(parents=True)
    for id, document in reviewed.items():
        (output / f'{id}.json').write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    manifest = {'source': provenance, 'reviewed_at': '2026-10-27', 'method': 'Source-checked annotation consistency corrections, independent of model predictions', 'changes': changes}
    (output / 'review_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('meta'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = reviewed_copy(args.source, args.output)
    print(json.dumps({'corrections': len(manifest['changes']), 'output': str(args.output), 'source_sha256': manifest['source']['sha256']}))


if __name__ == '__main__':
    main()
