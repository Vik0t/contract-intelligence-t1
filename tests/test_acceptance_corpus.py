"""Protect the exact published PMI inputs against accidental replacement."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


def test_published_pmi_corpus_matches_frozen_manifest():
    root = Path(__file__).resolve().parents[1]
    dataset = root / 'evals' / 'pmi-control-v1'
    payload = (dataset / 'manifest.json').read_bytes()
    expected = 'fae9bf7b07e6664b395a264441bb974f9db5b843070ced74f713017194227f77'
    assert sha256(payload).hexdigest() == expected
    assert (dataset / 'manifest.sha256').read_text().strip() == expected
    manifest = json.loads(payload)
    documents = manifest['documents']
    assert len({doc['id'] for doc in documents}) == len(documents) == 36
    assert Counter(doc['split'] for doc in documents) == {'development': 24, 'holdout': 12}
    assert Counter(doc['kind'] for doc in documents if doc['split'] == 'holdout') == {'typical': 8, 'atypical': 4}
    for doc in documents:
        assert set(doc['files']) == {'pdf', 'docx'}
        for extension, filename in doc['files'].items():
            source = dataset / filename
            assert source.parent == dataset and source.suffix == f'.{extension}'
            assert sha256(source.read_bytes()).hexdigest() == doc['sha256'][extension]
