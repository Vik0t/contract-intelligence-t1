"""Locate agreement headers and subjects without borrowing from appendices."""
from __future__ import annotations

import re

from src.extraction.context import PAGE_MARKER

DATE_LABEL_PATTERN = r'дата\s+(?:подписания(?:\s+договора)?|заключения(?:\s+договора)?|договора)\s*:'
PLACE_LABEL_PATTERN = r'место\s+(?:подписания|заключения)(?:\s+договора)?\s*:'

def header_region(text):
    markers = list(PAGE_MARKER.finditer(text))
    if markers and int(markers[0][1]) != 1:
        return ''
    first_page = text[:markers[1].start()] if len(markers) > 1 else text
    content = PAGE_MARKER.sub('', first_page).lstrip()
    if re.match(r'(?:приложение|сч[её]т|доверенность)\b', content, re.I):
        return ''
    boundary = re.search(
        r'(?im)^[ \t]*\d+(?:\.\d+)*\.[ \t]+\S|'
        r'\b(?:именуем\w*|в\s+лице|паспорт|ИНН|юридический\s+адрес)\b|'
        r'^[ \t]*(?!(?:'+PLACE_LABEL_PATTERN+'|'+DATE_LABEL_PATTERN+r'|номер\s+договора\s*:))'
        r'[А-ЯЁA-Z][А-Яа-яЁёA-Za-z /-]*:\s*|'
        r'^\s*(?:ООО|АО|ЗАО|ОАО|ПАО|Общество\s+с\s+ограниченной|'
        r'Физическое\s+лицо|Гражданин|Гражданка)\b', first_page,
    )
    return first_page[:boundary.start()] if boundary else first_page


def contract_heading(text):
    header = header_region(text)
    match = re.search(r'\b(?:трудовой\s+)?договор\b', header, re.I)
    if not match:
        return None
    lines = [line.strip() for line in header[match.start():].splitlines() if line.strip()]
    title = re.split(r'[.!?]\s+', lines[0], maxsplit=1)[0]
    continuation = re.compile(
        r'^(?:возмездного|оказания|поставки|перевозки|купли|подряда|хранения|'
        r'займа|страхования|транспортно-|коммерческой|образовательных|'
        r'гражданской|ответственности|имущества)\b', re.I,
    )
    for following in lines[1:]:
        # A subtitle can be a standalone parenthesized line below the number.
        # Keep it verbatim; do not search later body clauses for a title.
        subtitle = following.lstrip('(')
        if not continuation.match(subtitle):
            break
        title += ' ' + following
    title = re.split(r'\b(?:реквизиты\s+сторон|место\s+подписания|дата\s+подписания|стороны\s*:)', title, maxsplit=1, flags=re.I)[0]
    return title.strip()


def subject_region(text):
    appendix = re.search(r'(?im)^\s*ПРИЛОЖЕНИ[ЕЯ]\b', text)
    if appendix:
        text = text[:appendix.start()]
    # Prefer the actual subject section when general provisions precede it.
    # The latter are only a fallback for agreements without a subject heading.
    match = re.search(r'(?im)^\s*(?:\d+\.\s*)?ПРЕДМЕТ\s+ДОГОВОРА\b[^\n]*', text)
    if not match:
        match = re.search(r'(?im)^\s*(?:\d+\.\s*)?ОБЩИЕ\s+ПОЛОЖЕНИЯ\b[^\n]*', text)
    if not match:
        return ''
    end = re.search(r'(?im)^\s*(?:\d+\.\s+[^\d\s]|ПРИЛОЖЕНИ[ЕЯ]\b)', text[match.end():])
    return text[match.start():match.end() + end.start()] if end else text[match.start():]


def informative_subject_evidence(text, evidence):
    normalize = lambda s: ' '.join((s or '').casefold().split())
    return bool(evidence and normalize(evidence) in normalize(subject_region(text))
                and re.search(r'обязу\w*|предостав\w*|переда\w*|оказыва\w*|'
                              r'объект\w*\s+страхован\w*|предмет\w*\s+(?:явля\w*|составля\w*)', evidence, re.I))
