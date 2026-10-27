"""Load full document gold separately from legacy dataset/meta.json labels."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from src.evaluation import iso_date, missing

GOLD_FIELDS = {'contract_number', 'contract_date', 'contract_type', 'place', 'term', 'parties', 'total_amount', 'vat'}


def load_labels(path: Path):
    path = Path(path)
    if path.is_file():
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            raise ValueError('Legacy labels must be a list; use the meta directory for structured gold')
        labels = {}
        for row in rows:
            key = int(row['id'])
            if key in labels:
                raise ValueError(f'Duplicate label ID {key}')
            labels[key] = row['meta']
        return labels, {'format': 'legacy', 'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'contracts': len(labels)}
    files = sorted((p for p in path.glob('*.json') if p.stem.isdigit()), key=lambda p: int(p.stem))
    if not files:
        raise FileNotFoundError(f'No numbered labels in {path}. Download the separate meta.zip using tools/make_dataset.py --labels-only; legacy labels require --labels dataset/meta.json explicitly.')
    labels = {}
    source = hashlib.sha256()
    for p in files:
        data = json.loads(p.read_text(encoding='utf-8'))
        key = int(p.stem)
        if data.get('document_id') not in (key, str(key), f'contract_{key:03d}'):
            raise ValueError(f'Label filename/ID mismatch: {p.name}')
        if key in labels or not isinstance(data.get('gold'), dict) or set(data['gold']) != GOLD_FIELDS:
            raise ValueError(f'Invalid or duplicate structured gold: {p.name}')
        if not isinstance(data.get('files'), dict) or not data['files']:
            raise ValueError(f'Missing document filenames: {p.name}')
        for filename in data['files'].values():
            match = re.fullmatch(r'Договор_(\d+)\.(pdf|docx|png)', filename, re.I)
            if not match or int(match[1]) != key:
                raise ValueError(f'Wrong source document in {p.name}')
        g = data['gold']
        if not isinstance(g['parties'], list) or len(g['parties']) != 2:
            raise ValueError(f'Expected two gold parties in {p.name}')
        for field in GOLD_FIELDS - {'parties'}:
            if not isinstance(g[field], dict) or 'normalized_value' not in g[field]:
                raise ValueError(f'Missing normalized gold field {field} in {p.name}')
        for party in g['parties']:
            if any(not isinstance(party.get(field), dict) or 'normalized_value' not in party[field] for field in ('name','inn')):
                raise ValueError(f'Invalid party gold in {p.name}')
        for field in ('contract_date','term'):
            if not missing(g[field]['normalized_value']) and iso_date(g[field]['normalized_value']) is None:
                raise ValueError(f'Unparseable gold date {field} in {p.name}')
        if g['vat'].get('mode') not in (None, 'included', 'excluded', 'not_applicable', 'not_subject', 'not_stated'):
            raise ValueError(f'Unknown VAT annotation mode in {p.name}')
        labels[key] = data
        source.update(p.name.encode() + b'\0' + p.read_bytes())
    return labels, {'format': 'structured', 'path': str(path.resolve()), 'sha256': source.hexdigest(), 'contracts': len(labels)}
