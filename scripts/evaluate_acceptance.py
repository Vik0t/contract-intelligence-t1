"""Evaluate a frozen synthetic manifest using the exact four PMI attributes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from src.acceptance import SCORING_VERSION, metrics, score_attributes
from src.extraction.provenance import runtime_versions


def evaluate(dataset, output, *, split='holdout', backend='rules', review_policy='issued',
             transport='direct', base_url=None, token=None, timeout=60, poll_interval=.1, profile='pmi-rules-v1'):
    from backend.document_processing import parse_for_extraction
    from backend.config import Settings
    from backend.extraction import ExtractionService
    from backend.delivery_profile import validate_delivery_profile, runtime_source_sha256
    from src.extraction.reliability import assess_fields
    from scripts.acceptance_http import HttpAcceptanceRunner
    dataset, output = Path(dataset), Path(output)
    if output.exists():
        raise FileExistsError('Choose a new report path; existing evidence is never overwritten')
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError('Timeout and polling interval must be positive')
    if profile == 'pmi-rules-v1' and backend != 'rules':
        raise ValueError('pmi-rules-v1 requires backend=rules; use profile=custom for exploratory runs')
    if transport not in {'direct', 'http'} or (transport == 'http' and (not base_url or not token or profile != 'pmi-rules-v1')):
        raise ValueError('HTTP evaluation requires the pinned profile, base URL and session token')
    manifest_path = dataset / 'manifest.json'
    digest = sha256(manifest_path.read_bytes()).hexdigest()
    if (dataset / 'manifest.sha256').read_text().strip() != digest:
        raise ValueError('Manifest changed after freezing')
    manifest = json.loads(manifest_path.read_text())
    source_root = Path(__file__).resolve().parents[1]
    scoring_sources = [Path(__file__).resolve(), source_root / 'scripts' / 'acceptance_http.py',
                       source_root / 'src' / 'acceptance.py', source_root / 'src' / 'evaluation.py']
    scoring_hash = sha256(b''.join(path.name.encode() + b'\0' + path.read_bytes() for path in sorted(scoring_sources))).hexdigest()
    ids = [doc['id'] for doc in manifest['documents']]
    if len(ids) != len(set(ids)) or any(doc['split'] not in {'development', 'holdout'} for doc in manifest['documents']):
        raise ValueError('Invalid split or repeated contract ID')
    # Verify the entire selected input set before any uploads or extraction.
    selected = [doc for doc in manifest['documents'] if doc['split'] == split]
    if not selected:
        raise ValueError('Selected split is empty')
    for doc in selected:
        if set(doc['files']) != {'pdf', 'docx'}:
            raise ValueError('Each agreement requires both PDF and DOCX')
        for ext, filename in doc['files'].items():
            source = dataset / filename
            if (ext not in {'pdf', 'docx'} or source.parent.resolve() != dataset.resolve()
                    or not source.is_file() or sha256(source.read_bytes()).hexdigest() != doc['sha256'][ext]):
                raise ValueError(f'Input changed: {filename}')
    settings = Settings(_env_file=None, extraction_backend=backend, delivery_profile=profile,
        database_url='postgresql://unused/unused', allow_ocr_uploads=False,
        docx_use_rendered_pages=False, auto_extract_uploads=True, max_upload_size_mb=50, max_pdf_pages=200)
    configured = validate_delivery_profile(settings) if transport == 'direct' else {}
    service = ExtractionService(settings)
    runner = HttpAcceptanceRunner(base_url, token, timeout=timeout, poll_interval=poll_interval) if transport == 'http' else None
    runtime = runner.runtime if runner else {**configured, **runtime_versions(), 'runtime_source_sha256': runtime_source_sha256()}
    records = []
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': digest,
              'scoring_version': SCORING_VERSION,
              'scoring_sha256': scoring_hash,
              'backend': backend, 'split': split, 'review_policy': review_policy, 'transport': transport,
              'delivery_profile': runtime['profile'], 'profile_sha256': runtime['profile_sha256'],
              'runtime_source_sha256': runtime['runtime_source_sha256'],
              'timing_scope': 'upload through first persisted result returned by GET' if runner else 'validation, parsing and extraction; no HTTP or database',
              'counting_unit': 'contract; all PDF and DOCX versions must be correct',
              'recall_policy': 'wrong issued value counts as FP and FN',
              'absence_policy': 'absent gold and absent answer: no TP/FP/FN; an invented answer: FP only',
              'gold_review': manifest.get('gold_review'), 'rules_sha256': runtime['rules_sha256'],
              'dependencies': runtime['dependencies'], 'records': records}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for doc in selected:
            record = {'id': doc['id'], 'kind': doc['kind'], 'template_group': doc['template_group'], 'files': []}
            for ext, filename in doc['files'].items():
                source = dataset / filename
                if source.parent.resolve() != dataset.resolve() or sha256(source.read_bytes()).hexdigest() != doc['sha256'][ext]:
                    raise ValueError(f'Input changed: {filename}')
                started = time.perf_counter()
                fields = {}
                item = {'format': ext, 'filename': filename}
                try:
                    if runner:
                        item.update(runner.run(source, ext))
                        fields = item['fields']
                    else:
                        from backend.file_validation import validate_document_file
                        validate_document_file(source, source.suffix, max_pdf_pages=settings.max_pdf_pages, allow_ocr=settings.allow_ocr_uploads)
                        text, document = parse_for_extraction(source, settings)
                        fields, _ = service.extract(text=text, document_ir=document)
                        fields = assess_fields(fields, text, document=document, reference_date=datetime.now(timezone.utc))
                        item.update(status='ok', pages=len(document.pages), fields=fields)
                except Exception as exc:
                    item.update(status='error', error_type=type(exc).__name__)
                item.setdefault('seconds', time.perf_counter() - started)
                item['scores'] = score_attributes(doc['gold'], fields, review_policy=review_policy)
                record['files'].append(item)
            records.append(record)
            # Preserve every completed agreement if a long local-model run is interrupted.
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if runner and runner.get('runtime/profile') != runner.runtime:
            raise ValueError('Server runtime changed during evaluation')
    finally:
        if runner:
            runner.close()
    report['metrics'] = metrics(records)
    report['atypical'] = metrics([record for record in records if record['kind'] == 'atypical'])
    report['by_template'] = {group: metrics([r for r in records if r['template_group'] == group]) for group in sorted({r['template_group'] for r in records})}
    report['errors'] = sum(item['status'] != 'ok' for r in records for item in r['files'])
    report['max_processing_seconds'] = max(item['seconds'] for r in records for item in r['files'])
    precision_ok = all(item['precision'] is not None and item['precision'] >= .95 for item in report['metrics']['attributes'].values())
    report['quality_thresholds_met'] = precision_ok and (report['metrics']['typical_all_four_rate'] or 0) >= .8
    report['performance_threshold_met'] = report['max_processing_seconds'] <= runtime['profile']['processing_limit_seconds']
    report['formal_acceptance_ready'] = (report['quality_thresholds_met'] and report['performance_threshold_met'] and not report['errors']
                                          and transport == 'http' and profile == 'pmi-rules-v1'
                                          and split == 'holdout' and report['gold_review'] == 'manually_verified')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {key: value for key, value in report.items() if key not in {'records', 'dependencies', 'by_template'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=['development', 'holdout'], default='holdout')
    parser.add_argument('--backend', choices=['rules', 'local'], default='rules')
    parser.add_argument('--profile', choices=['pmi-rules-v1', 'custom'], default='pmi-rules-v1')
    parser.add_argument('--transport', choices=['direct', 'http'], default='direct')
    parser.add_argument('--base-url', help='API base URL, including /api when using the Compose gateway')
    parser.add_argument('--token-env', default='PMI_SESSION_TOKEN', help='Environment variable containing an existing session token')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--poll-interval', type=float, default=.1)
    parser.add_argument('--review-policy', choices=['issued', 'abstain'], default='issued')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.dataset, args.output, split=args.split, backend=args.backend, review_policy=args.review_policy,
        transport=args.transport, base_url=args.base_url, token=os.getenv(args.token_env),
        timeout=args.timeout, poll_interval=args.poll_interval, profile=args.profile), ensure_ascii=False, indent=2))
