"""Recover only unambiguous, source-labelled or conventional header facts."""
from __future__ import annotations

import re
from src.extraction.context import evidence_pages
from src.extraction.source_context import header_region, contract_heading, DATE_LABEL_PATTERN, PLACE_LABEL_PATTERN
from src.extraction.postprocess import _extract_date_candidates

DATE_LABEL = re.compile(DATE_LABEL_PATTERN, re.I)
PLACE_LABEL = re.compile(PLACE_LABEL_PATTERN, re.I)
NUMBER_TOKEN = r'[А-Яа-яЁёA-Za-z0-9][А-Яа-яЁёA-Za-z0-9/._-]*'


def _number_options(header, lines):
    options = {}
    heading = contract_heading(header)
    if heading:
        for match in re.finditer(r'№\s*(?P<number>'+NUMBER_TOKEN+r')|^договор\s+(?P<bare>\d[А-Яа-яЁёA-Za-z0-9/._-]*)', heading, re.I):
            value = (match['number'] or match['bare']).rstrip('.')
            if value and value.casefold() not in {'не','нет','б/н'} and not value.endswith(('-', '/')):
                options[value] = heading[:match.end()]
    for index, line in enumerate(lines):
        label = re.search(r'номер\s+договора\s*:', line, re.I)
        if not label:
            continue
        tail = line[label.end():].strip()
        if tail:
            match = re.match(NUMBER_TOKEN, tail)
            if match and match[0].casefold() not in {'не','нет','б/н'}:
                raw_tail = line[label.end():]
                offset = len(raw_tail) - len(raw_tail.lstrip())
                options[match[0].rstrip('.')] = line[:label.end() + offset + match.end()]
        elif index + 1 < len(lines):
            following = lines[index + 1]
            # Flattened header columns can put the date below the number label.
            # A date-looking next row is ambiguous; never attach it as a number.
            if re.fullmatch(NUMBER_TOKEN, following) and not _extract_date_candidates(following):
                options[following.rstrip('.')] = line + '\n' + following
    return options


def _city(value, labelled=False):
    value = value.strip(' \t|;,:«»"“”')
    match = re.match(r'^(?:г\.\s*|город\s+)(.+)', value, re.I)
    if match:
        value = match[1].strip()
    elif not labelled:
        return None
    if not re.fullmatch(r'[А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]*(?:\s+[А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]*)*', value):
        return None
    return value


def recover_header_fields(result, text):
    header = header_region(text)
    lines = [line.strip() for line in header.splitlines() if line.strip() and not re.fullmatch(r'PAGE\s+\d+', line.strip())]
    candidates = {'contract_number': _number_options(header, lines), 'contract_date': {}, 'place': {}}
    for index, line in enumerate(lines):
        date_label, place_label = DATE_LABEL.search(line), PLACE_LABEL.search(line)
        rows = [line]
        if (date_label or place_label) and index + 1 < len(lines):
            rows.append(lines[index + 1])
        for row in rows:
            # Dates from a contract number, identity document or body are never
            # candidates. A date row must have an explicit label or a city prefix.
            clean = row.replace('|', ' ')
            conventional = bool(re.match(r'^(?:г\.\s*|город\s+)', clean, re.I))
            if row != line and re.match(r'^(?:договор\b|номер\b|№)', clean, re.I):
                continue
            if not (date_label or place_label or conventional):
                continue
            dates = _extract_date_candidates(clean)
            if len({d['value'] for d in dates}) == 1 and (date_label or conventional):
                candidates['contract_date'][dates[0]['value']] = row
            city_text = clean
            place_in_row = PLACE_LABEL.search(city_text)
            if place_in_row:
                city_text = city_text[place_in_row.end():]
            city_dates = _extract_date_candidates(city_text)
            if city_dates:
                city_text = city_text[:city_dates[0]['start']]
            city_text = DATE_LABEL.sub('', city_text)
            city = _city(city_text, labelled=bool(place_label))
            if city and (place_label or (conventional and len(dates) == 1)):
                candidates['place'][city] = row
        # Conventional two-line heading: city, then just the signing date.
        city = _city(line)
        if city and index + 1 < len(lines):
            following = lines[index + 1]
            dates = _extract_date_candidates(following)
            if len(dates) == 1:
                rest = following[:dates[0]['start']] + following[dates[0]['end']:]
                if re.fullmatch(r'[\s«»"“”.,]*(?:г(?:ода)?\.?)?[\s«»"“”.,]*', rest, re.I):
                    quote = line + '\n' + following
                    candidates['contract_date'][dates[0]['value']] = quote
                    candidates['place'][city] = quote
    for key, options in candidates.items():
        item = result.get(key)
        if not isinstance(item, dict):
            continue
        if key == 'contract_number' and item.get('value') and options:
            normalize = lambda s: ''.join(s.split()).lstrip('№').casefold()
            current = normalize(item['value'])
            if len(options) == 1:
                value, quote = next(iter(options.items()))
                actual = normalize(value)
                if current == actual:
                    continue
                if actual.startswith(current):
                    item['source_correction'] = {'previous_value': item['value'], 'reason': 'truncated_identifier'}
                    item.update(value=None, status='needs_review', reason='Восстановлен полный номер из шапки договора')
                else:
                    item.update(status='needs_review', reason='Номер модели расходится с шапкой договора',
                                candidates=[{'value': item['value'], 'evidence': item.get('evidence')}, {'value': value, 'evidence': quote}])
                    continue
            else:
                item.update(status='needs_review', reason='В шапке найдены разные номера договора',
                            candidates=[{'value': v, 'evidence': q} for v,q in options.items()])
                continue
        if item.get('value') not in (None, ''):
            continue
        if len(options) == 1:
            value, evidence = next(iter(options.items()))
            pages = evidence_pages(text, evidence)
            item.update(value=value, evidence=evidence, page_number=pages[0] if len(pages) == 1 else None,
                        method='rule', rule_id='agreement-header-v1')
        elif len(options) > 1:
            item.update(status='needs_review', reason='В шапке найдены противоречивые значения',
                        candidates=[{'value': value, 'evidence': quote} for value, quote in options.items()])
    return result
