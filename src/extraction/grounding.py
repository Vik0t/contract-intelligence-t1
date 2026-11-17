"""Match quotes across physical word wraps, never across altered words or digits."""
from __future__ import annotations

import re


def source_quote(text: str, evidence: str) -> str | None:
    if not evidence or not evidence.strip():
        return None
    normalize = lambda value: ' '.join(value.casefold().split())
    if normalize(evidence) in normalize(text):
        return evidence
    # Two exact typography interpretations: a genuine compound keeps its
    # hyphen, while a word split for pagination loses the discretionary hyphen.
    wraps = list(re.finditer(r'(?<=[A-Za-zА-Яа-яЁё])[-\u00ad][ \t]*\r?\n\s*(?=[A-Za-zА-Яа-яЁё])', text))
    if not wraps:
        return None
    for keep_hyphen in (True, False):
        skip = set()
        for match in wraps:
            skip.update(range(match.start() + (1 if keep_hyphen else 0), match.end()))
        chars, offsets = [], []
        for index, char in enumerate(text):
            if index in skip:
                continue
            for folded in char.casefold():
                folded = ' ' if folded.isspace() else folded
                if folded == ' ' and (not chars or chars[-1] == ' '):
                    continue
                chars.append(folded); offsets.append(index)
        needle = normalize(evidence)
        start = ''.join(chars).find(needle)
        if start >= 0:
            return text[offsets[start]:offsets[start + len(needle) - 1] + 1]
    return None
