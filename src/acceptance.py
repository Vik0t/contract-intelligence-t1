"""Four-attribute PMI metrics, with explicit handling of review and party roles."""
from src.evaluation import amount, iso_date, name, number
from src.extraction.reliability import CORE_FIELDS, canonical_role

SCORING_VERSION = 'pmi-four-attributes-v2'


def _present(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def score_attributes(gold, fields, *, review_policy='issued'):
    if review_policy not in {'issued', 'abstain'}:
        raise ValueError('Unknown review policy')
    predicted = {}
    for key in CORE_FIELDS:
        value = fields.get(key)
        status = fields.get('_quality', {}).get(key, {}).get('status')
        if key == 'parties':
            expected = gold[key] or []
            expected_present = bool(expected)
            value = value if isinstance(value, list) else []
            issued = bool(value)
            def identities(parties):
                return sorted((name(p.get('name')), canonical_role(p.get('role')) or p.get('canonical_role') or '', (p.get('role') or '').casefold()) for p in parties)
            matches = identities(expected) == identities(value)
        else:
            value = value if isinstance(value, dict) else {}
            status = value.get('status', status)
            issued = _present(value.get('value'))
            expected = gold[key]
            expected_present = _present(expected.get('value')) if key == 'total_amount' else _present(expected)
            if key == 'contract_number':
                matches = number(value.get('value')) == number(expected)
            elif key == 'contract_date':
                matches = iso_date(value.get('value')) == iso_date(expected) and iso_date(expected) is not None
            else:
                issued = issued or _present(value.get('currency'))
                matches = amount(value.get('value')) == amount(expected.get('value')) and value.get('currency') == expected.get('currency')
        if review_policy == 'abstain' and status != 'found':
            issued = False
        correct = issued and matches if expected_present else not issued
        predicted[key] = {'issued': issued, 'correct': bool(correct), 'expected_present': expected_present}
    return predicted


def metrics(records):
    """Count an agreement once. Every supplied format must agree with gold."""
    totals = {key: {'tp': 0, 'fp': 0, 'fn': 0} for key in CORE_FIELDS}
    typical = correct_typical = 0
    for record in records:
        checks = {}
        for key in CORE_FIELDS:
            attempts = [item['scores'][key] for item in record['files']]
            # Old saved scores assumed every gold attribute existed. Keep those
            # records readable, without applying that assumption to new scores.
            presence = {item.get('expected_present', True) for item in attempts}
            if len(presence) > 1:
                raise ValueError(f'Inconsistent gold presence for {key}')
            expected_present = next(iter(presence), True)
            correct = bool(attempts) and all(item['scores'][key]['correct'] and item.get('status', 'ok') == 'ok' for item in record['files'])
            totals[key]['tp'] += int(expected_present and correct)
            # A correct answer in one format and abstention in another is a
            # missed agreement-level result, not a false issued value.
            totals[key]['fp'] += int(any(item['issued'] and not item['correct'] for item in attempts))
            # A wrong answer also misses the gold value (standard extraction recall).
            totals[key]['fn'] += int(expected_present and not correct)
            checks[key] = correct
        if record['kind'] == 'typical':
            typical += 1
            correct_typical += int(all(checks.values()))
    for counts in totals.values():
        counts['precision'] = counts['tp'] / (counts['tp'] + counts['fp']) if counts['tp'] + counts['fp'] else None
        counts['recall'] = counts['tp'] / (counts['tp'] + counts['fn']) if counts['tp'] + counts['fn'] else None
    return {'contracts': len(records), 'attributes': totals, 'typical_contracts': typical,
            'correct_typical_contracts': correct_typical, 'typical_all_four_rate': correct_typical / typical if typical else None}
