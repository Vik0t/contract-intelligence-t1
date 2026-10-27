"""Conservative party identity and INN linkage; no annotation dependencies."""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

from src.extraction.context import evidence_pages

LEGAL_FORMS = {
    'общество с ограниченной ответственностью': 'ооо',
    'публичное акционерное общество': 'пао',
    'закрытое акционерное общество': 'зао',
    'открытое акционерное общество': 'оао',
    'акционерное общество': 'ао',
    'индивидуальный предприниматель': 'ип',
}


def identity(name):
    value = ' '.join(unicodedata.normalize('NFKC', name or '').casefold().replace('ё', 'е').split())
    for full, short in LEGAL_FORMS.items():
        if value.startswith(full + ' '):
            value = short + value[len(full):]
            break
    value = re.sub(r'^[оo]{3}(?=\s)', 'ооо', value)
    return value.translate(str.maketrans('', '', '«»"“”')).strip()


def merge_parties(first, later):
    """A shared INN never collapses two different named entities."""
    merged = deepcopy(first)
    for party in later:
        key = identity(party.get('name'))
        candidates = [p for p in merged if key and identity(p.get('name')) == key]
        if not candidates and party.get('inn'):
            candidates = [p for p in merged if p.get('inn') == party['inn']
                          and (not key or not identity(p.get('name')))]
        # Conflicting tax IDs for one name are retained as separate candidates.
        candidates = [p for p in candidates if not p.get('inn') or not party.get('inn') or p['inn'] == party['inn']]
        if len(candidates) == 1:
            existing = candidates[0]
            for field, value in party.items():
                if existing.get(field) is None:
                    existing[field] = deepcopy(value)
        else:
            merged.append(deepcopy(party))
    return merged


def name_spans(name, text):
    key = identity(name)
    if not key:
        return []
    aliases = {key}
    for full, short in LEGAL_FORMS.items():
        if key.startswith(short + ' '):
            aliases.add(full + key[len(short):])
    matches = []
    for alias in aliases:
        tokens = alias.split()
        pattern = r'[\s«»"“”]+'.join(re.escape(token) for token in tokens)
        if alias.startswith('ооо '):
            pattern = '[оo]{3}' + pattern[3:]
        matches.extend(re.finditer(r'(?<!\w)' + pattern + r'(?!\w)', text, re.I))
    return sorted(matches, key=lambda m: m.start())


def inn_in_evidence(inn, evidence):
    return bool(isinstance(inn, str) and re.fullmatch(r'\d{10}|\d{12}', inn)
                and re.search(r'(?<!\d)' + r'\s*'.join(inn) + r'(?!\d)', evidence or ''))


def _labelled_records(parties, text):
    """A role-labelled record can contain ID fields between name and INN.

    Only an exact name-only row followed by personal/company identifiers is
    accepted. Bank data, another actor or another tax ID makes it ambiguous.
    """
    lines = text.splitlines()
    known = {identity(p['name']): p['name'] for p in parties if p.get('name')}
    boundary = re.compile(r'^\s*(?:[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\s/-]*:\s*|PAGE\s+\d+|\d+\.\s+\S.*)\s*$')
    identifier = re.compile(r'^(?:паспорт|СНИЛС|КПП|ОГРН(?:ИП)?|дата\s+рождения|'
                            r'гражданство|адрес(?:\s+(?:регистрации|проживания))?|'
                            r'(?:юридический|почтовый|фактический)\s+адрес)\s*:', re.I)
    proofs = {}
    for party in parties:
        name, role = party.get('name'), party.get('role')
        if not name or not role:
            continue
        for index, line in enumerate(lines):
            if identity(line.strip().rstrip(':').strip(' «»"')) != identity(role):
                continue
            if not line.rstrip().endswith(':'):
                continue
            stop = next((i for i in range(index + 1, len(lines)) if boundary.fullmatch(lines[i].strip())), len(lines))
            rows = [row.strip() for row in lines[index + 1:stop] if row.strip()]
            if not rows or identity(rows[0].strip(' ,.;')) != identity(name):
                continue
            record = '\n'.join(rows)
            if any(key != identity(name) and name_spans(other, record) for key, other in known.items()):
                continue
            inns = re.findall(r'\bИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)', record, re.I)
            if len(set(inns)) != 1:
                continue
            for position, row in enumerate(rows[1:], 1):
                if re.fullmatch(r'ИНН\s*[:№]?\s*\d{10}(?:\d{2})?\s*[.;]?', row, re.I):
                    proofs.setdefault(identity(name), {})[inns[0]] = '\n'.join(rows[:position + 1])
                    break
                if not identifier.match(row):
                    break
    return proofs


def source_links(parties, text):
    """Link only direct name/INN records, never the nearest arbitrary number.

    Parenthesized preambles and a name followed immediately by an INN row are
    supported. Flattened two-column rows containing both names are ambiguous.
    """
    known = {identity(p['name']): p['name'] for p in parties if p.get('name')}
    proofs = {}
    inn_pattern = re.compile(r'\bИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)', re.I)
    for key, name in known.items():
        for match in name_spans(name, text):
            # The entire physical name row must belong to just this party.
            start = text.rfind('\n', 0, match.start()) + 1
            end = text.find('\n', match.end())
            end = len(text) if end < 0 else end
            row = text[start:end]
            prefix = text[start:match.start()].strip()
            if prefix and not prefix.endswith(':'):
                continue
            if any(other != key and name_spans(other_name, row) for other, other_name in known.items()):
                continue
            tail = text[match.end():]
            direct = re.match(r'["»”]?\s*[,;(]?\s*ИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)', tail, re.I)
            if direct:
                inn = direct[1]
                quote = text[match.start():match.end() + direct.end()]
            else:
                # Name-only row, then the next nonempty row is explicitly INN.
                if text[match.end():end].strip(' \t«»"“”,.;:'):
                    continue
                following = re.match(r'\s*ИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)[^\n]*', text[end:], re.I)
                if not following:
                    continue
                inn = following[1]
                quote = text[match.start():end + following.end()]
            if len(inn_pattern.findall(quote)) == 1:
                proofs.setdefault(key, {})[inn] = quote
    for key, records in _labelled_records(parties, text).items():
        proofs.setdefault(key, {}).update(records)
    return proofs


def link_from_source(parties, text, document=None):
    result = merge_parties([], parties)
    proofs = {key: {inn: {'evidence': quote, 'page': next(iter(evidence_pages(text, quote)), None),
                         'method': 'direct_name_inn_record'} for inn, quote in records.items()}
              for key, records in source_links(result, text).items()}
    if document is not None:
        from src.extraction.party_sources import layout_links
        for key, records in layout_links(result, text, document).items():
            # Native records / explicit columns retain information that a
            # flattened text row may have destroyed. Prefer that source proof.
            proofs[key] = records
    issues = []
    for party in result:
        key = identity(party.get('name'))
        candidates = proofs.get(key, {})
        if len(candidates) == 1:
            inn, proof = next(iter(candidates.items()))
            if not party.get('inn'):
                party.update(inn=inn, inn_evidence=proof['evidence'], inn_page_number=proof['page'], inn_link=proof)
            elif party['inn'] != inn:
                issues.append('Извлечённый ИНН противоречит реквизитам стороны')
                party['inn_candidates'] = [{'value': party['inn'], 'evidence': party.get('inn_evidence')},
                                           {'value': inn, **proof}]
        elif len(candidates) > 1:
            issues.append('Для одной стороны найдены различные ИНН')
    result = merge_parties([], result)
    by_inn = {}
    for party in result:
        if party.get('inn') and party.get('name'):
            by_inn.setdefault(party['inn'], set()).add(identity(party['name']))
    if any(len(names) > 1 for names in by_inn.values()):
        issues.append('Один ИНН сопоставлен разным названиям сторон')
    by_name = {}
    for party in result:
        if party.get('inn') and party.get('name'):
            by_name.setdefault(identity(party['name']), set()).add(party['inn'])
    if any(len(inns) > 1 for inns in by_name.values()):
        issues.append('Для одной стороны найдены различные ИНН')
    return result, sorted(set(issues))
