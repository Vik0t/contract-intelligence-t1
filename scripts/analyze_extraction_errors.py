"""Private error inventory and exploratory postprocessing replay; never calls a model."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.evaluation import FIELDS, score_gold, summarize
from src.evaluation_labels import load_labels
from src.extraction.postprocess import postprocess_extraction


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(results: Path, labels_path: Path, *, replay=False):
    labels, provenance = load_labels(labels_path)
    manifest_path = results / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get('completed'):
        raise ValueError('A completed source manifest is required')
    entries = {(item['document_id'], item['format']): item for item in manifest['files']}
    output = {'created_at': datetime.now(timezone.utc).isoformat(), 'labels': provenance,
              'manifest_sha256': sha256(manifest_path),
              'postprocessor_sha256': sha256(Path(__file__).resolve().parents[1] / 'src/extraction/postprocess.py'),
              'method': 'Saved final predictions, fixed evaluation rules, no new inference',
              'limitations': ['Development corpus, not an independent held-out test.',
                              'No raw per-chunk model outputs: missing final fields cannot be attributed uniquely to model or validation.',
                              'Replay applies postprocessing to merged outputs and full cached text; it is not a production inference rerun.'],
              'models': {}}
    for backend in ('local', 'api'):
        report_path = results / f'{backend}.json'
        source = json.loads(report_path.read_text())
        if not source.get('completed'):
            raise ValueError(f'Incomplete {backend} report')
        if any(r['document_id'] not in labels for r in source['records']):
            raise ValueError('All report documents must have labels')
        records = deepcopy(source['records'])
        errors = []
        per_field = {}
        for record in records:
            gold = labels[record['document_id']]
            record['field_scores'] = score_gold(gold, record['fields']) if record['status'] == 'ok' else dict.fromkeys(FIELDS, False)
            for field, passed in record['field_scores'].items():
                if passed is False:
                    errors.append({'document_id': record['document_id'], 'format': record['format'], 'field': field})
        for field in FIELDS:
            matches = [row for row in errors if row['field'] == field]
            per_field[field] = {'errors': len(matches), 'contracts': len({row['document_id'] for row in matches}),
                                'formats': dict(Counter(row['format'] for row in matches))}
        analysis = {'source_report_sha256': sha256(report_path), 'config': source['config'],
                    'baseline': summarize(records), 'error_inventory': per_field, 'errors': errors}
        if replay:
            before = {(r['document_id'], r['format']): r['field_scores'] for r in records}
            changes = []
            for record in records:
                if record['status'] != 'ok':
                    continue
                entry = entries[(record['document_id'], record['format'])]
                cache = json.loads(Path(entry['cache']).read_text())
                if hashlib.sha256(cache['text'].encode()).hexdigest() != record.get('input_hash') or record.get('input_hash') != entry.get('input_hash'):
                    raise ValueError('Cached text differs from saved model input')
                record['fields'] = postprocess_extraction(record['fields'], cache['text'])
                record['field_scores'] = score_gold(labels[record['document_id']], record['fields'])
                previous = before[(record['document_id'], record['format'])]
                for field, passed in record['field_scores'].items():
                    if passed != previous[field]:
                        changes.append({'document_id': record['document_id'], 'format': record['format'],
                                        'field': field, 'before': previous[field], 'after': passed})
            analysis['exploratory_replay'] = {'summary': summarize(records), 'changes': changes,
                                              'fixed_checks': sum(c['after'] is True for c in changes),
                                              'regressed_checks': sum(c['after'] is False for c in changes)}
        output['models'][backend] = analysis
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--labels', type=Path, default=Path('meta'))
    parser.add_argument('--replay-postprocess', action='store_true')
    parser.add_argument('--output', type=Path, required=True, help='Private JSON, normally under ignored tmp/')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a new output file; preserve existing reports')
    result = analyze(args.results, args.labels, replay=args.replay_postprocess)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for backend, data in result['models'].items():
        replay = data.get('exploratory_replay', {})
        print(json.dumps({'backend': backend, 'errors': len(data['errors']),
                          'replay_fixed_checks': replay.get('fixed_checks'),
                          'replay_regressed_checks': replay.get('regressed_checks')}))


if __name__ == '__main__':
    main()
