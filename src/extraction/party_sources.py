"""Identity proofs from source paragraph order and explicit PDF columns."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from src.extraction.party_resolution import identity, name_spans, source_links
from src.extraction.context import evidence_pages


def layout_links(parties, text, document):
    path = Path(document.source_path)
    if not path.is_file() or len({identity(p.get('name')) for p in parties if p.get('name')}) < 2:
        return {}
    normalize = lambda s: ' '.join(s.casefold().split())
    results = {}
    digest = None

    def add(key, inn, evidence, page, method):
        nonlocal digest
        if normalize(evidence) not in normalize(text):
            return
        digest = digest or hashlib.sha256(path.read_bytes()).hexdigest()
        results.setdefault(key, {})[inn] = {'evidence': evidence, 'page': page,
                                           'method': method, 'source_sha256': digest}

    if path.suffix.lower() == '.docx':
        from docx import Document
        # Native paragraph order may differ from a rendered PDF's two columns.
        source = '\n'.join(p.text for p in Document(path).paragraphs)
        for key, records in source_links(parties, source).items():
            for inn, record in records.items():
                mention = re.search(r'\bИНН\s*[:№]?\s*' + re.escape(inn), record, re.I)
                if mention:
                    evidence = mention[0]
                    pages = evidence_pages(text, evidence)
                    add(key, inn, evidence, pages[0] if len(pages) == 1 else None, 'native_requisites_record')
        return results
    if path.suffix.lower() != '.pdf':
        return results

    import pymupdf
    with pymupdf.open(path) as pdf:
        for number, page in enumerate(pdf, 1):
            words = page.get_text('words', sort=True)
            flat = ''; spans = []
            for word in words:
                start = len(flat)
                flat += word[4] + ' '
                spans.append((start, len(flat), word))
            if not re.search(r'реквизит|подписи\s+сторон|адреса\s+сторон', flat, re.I):
                continue
            anchors = []
            for party in parties:
                if not party.get('name'):
                    continue
                for match in name_spans(party['name'], flat):
                    hit = [w for start, end, w in spans if start < match.end() and end > match.start()]
                    anchors.append((identity(party['name']), min(w[0] for w in hit), max(w[2] for w in hit),
                                    min(w[1] for w in hit), max(w[3] for w in hit)))
            for left in anchors:
                for right in anchors:
                    # Both named columns must have an explicit common name row.
                    if left[0] == right[0] or left[2] >= right[1] or abs(left[3] - right[3]) > min(left[4]-left[3], right[4]-right[3]) / 2:
                        continue
                    boundary = (left[2] + right[1]) / 2
                    for anchor, column in ((left, 'left'), (right, 'right')):
                        matches = {}
                        for mention in re.finditer(r'\bИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)', flat, re.I):
                            hit = [w for start, end, w in spans if start < mention.end() and end > mention.start()]
                            if min(w[1] for w in hit) <= anchor[3]:
                                continue
                            x0, x1 = min(w[0] for w in hit), max(w[2] for w in hit)
                            if (column == 'left' and x1 < boundary) or (column == 'right' and x0 > boundary):
                                matches[mention[1]] = mention[0]
                        if len(matches) == 1:
                            inn, evidence = next(iter(matches.items()))
                            add(anchor[0], inn, evidence, number, 'same_requisites_column')
    return results
