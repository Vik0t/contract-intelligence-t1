"""Recover missing values only from explicit, unambiguous source statements."""
from __future__ import annotations

import re

from src.extraction.context import evidence_pages
from src.extraction.reliability import total_candidates


def recover_explicit_facts(result, text):
    # Appendices can describe their own sums and tax treatment.
    main = re.split(r'(?im)^\s*ПРИЛОЖЕНИ[ЕЯ]\b', text, maxsplit=1)[0]
    amount = result.get('total_amount')
    if isinstance(amount, dict) and amount.get('value') is None:
        candidates = [c for c in total_candidates(main) if not re.search(
            r'оклад|ежемесячн|в\s+месяц|за\s+(?:один\s+)?(?:месяц|час|день|единиц)|аванс|предоплат|штраф|неустойк',
            c['evidence'], re.I)]
        if len({c['value'] for c in candidates}) == 1:
            candidate = candidates[0]
            if candidate['value'] > 0:
                amount.update(candidate, method='rule', rule_id='explicit-contract-total-v1')
        elif candidates:
            amount.update(status='needs_review', reason='Найдены разные общие суммы договора', candidates=candidates)

    vat = result.get('vat')
    if not isinstance(vat, dict) or vat.get('mode') not in (None, 'not_stated') or vat.get('rate') is not None:
        return result
    # A tax regime, zero rate or unpaid loan is not an explicit VAT exemption.
    # Keep the original quote, including physical line breaks.
    exemption = re.compile(
        r'\bНДС\s+не\s+облага[ею]тся\b|'
        r'\bне\s+облага[ею]тся\s+(?:налогом\s+на\s+добавленную\s+стоимость|НДС)\b|'
        r'\bосвобожден\w*\s+от\s+(?:уплаты\s+)?(?:налога\s+на\s+добавленную\s+стоимость|НДС)\b', re.I)
    matches = []
    for match in exemption.finditer(main):
        # An exemption stated only as a condition/possibility, or explicitly
        # negated, is not the actual VAT treatment of the agreement.
        before = main[:match.start()]
        boundary = list(re.finditer(r'[.!?;](?=\s|$)|(?m:^PAGE\s+\d+\s*$)', before))
        start = boundary[-1].end() if boundary else 0
        prefix = main[start:match.start()]
        end = re.search(r'[.!?;](?=\s|$)|(?m:^PAGE\s+\d+\s*$)', main[match.end():])
        clause = main[start:match.end() + end.start()] if end else main[start:]
        if (re.search(r'\bне\s*$', prefix, re.I)
                or re.search(r'\bесли\b|в\s+случае|при\s+условии|\bможет\b|\bмогут\b|\bвправе\b', clause, re.I)):
            continue
        matches.append(match)
    # Mixed/inconsistent tax statements require an operator's decision.
    contrary = re.search(r'(?:включая|в\s+том\s+числе|сверх\s+\w+|плюс)\s+НДС|'
                         r'НДС\s*(?:по\s+ставке\s*)?\d+(?:[.,]\d+)?\s*%|'
                         r'ставк\w*\s+НДС\s*[:—-]?\s*\d+', main, re.I)
    if matches and not contrary:
        quote = matches[0][0]
        pages = evidence_pages(text, quote)
        vat.update(mode='not_subject', rate=None, raw_value=quote, evidence=quote,
                   page_number=pages[0] if len(pages) == 1 else None,
                   method='rule', rule_id='explicit-vat-exemption-v1')
    elif matches and contrary:
        vat.update(status='needs_review', reason='В источнике найдены разные условия НДС')
    return result
