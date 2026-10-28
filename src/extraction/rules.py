"""Conservative baseline for text-layer contracts; no model or external service."""
from __future__ import annotations

import re
from src.extraction.postprocess import _date_from_text
from src.extraction.reliability import assess_fields, total_candidates
from src.extraction.validation import validate_model_result

ROLES = r'Заказчик|Исполнитель|Покупатель|Поставщик|Подрядчик|Арендатор|Арендодатель|За[её]мщик|Займодавец|Поклажедатель|Хранитель'
ORG = r'(?:ООО|ПАО|АО|ЗАО|ОАО)\s*["«][^"»]+["»]|(?:ИП|Индивидуальный предприниматель)\s+[^,;|\n]+'
CURRENCIES = {'RUB': r'\bRUB\b|руб|₽', 'USD': r'\bUSD\b|доллар|\$', 'EUR': r'\bEUR\b|евро|€',
              'CNY': r'\bCNY\b|юан', 'KZT': r'\bKZT\b|тенге|₸', 'GBP': r'\bGBP\b|фунт|£'}


def extract_with_rules(text: str, document_ir=None):
    result = {}
    lines = text.splitlines()
    heading = re.compile(r'^\s*(?:договор|контракт)\b[^\n№]{0,100}№\s*([^\s,;]+)', re.I)
    headers = [(i, heading.search(line)) for i, line in enumerate(lines) if heading.search(line)]
    if headers:
        index, match = headers[0]
        result['contract_number'] = {'value': match[1].rstrip('.'), 'evidence': lines[index]}
        # A date belongs to the agreement header only; never search payment and appendix sections.
        date_lines = [line for line in lines[index:index + 7] if line.strip() and not line.startswith('PAGE ')]
        for line in date_lines[:3]:
            if re.search(r'сч[её]т|приложени|доверенност|аванс|оплат|действует\s+до', line, re.I):
                break
            value = _date_from_text(line)
            if value:
                result['contract_date'] = {'value': value, 'evidence': line}
                break
        numbers = {match[1].rstrip('.') for _, match in headers}
        if len(numbers) > 1:
            result['contract_number']['candidates'] = [{'value': m[1].rstrip('.'), 'evidence': lines[i]} for i, m in headers]
    parties = []
    for line in lines:
        for match in re.finditer(rf'\b(?P<role>{ROLES})\s*[:|\-]\s*(?P<name>{ORG})', line, re.I):
            parties.append({'name': match['name'].strip(), 'role': match['role'], 'name_evidence': line})
        # Conventional preamble: ООО "Альфа", именуемое ... "Заказчик".
        for match in re.finditer(rf'(?P<name>{ORG})\s*,[^\n;]{{0,140}}?именуем\w*[^\n;]{{0,50}}?["«](?P<role>{ROLES})["»]', line, re.I):
            parties.append({'name': match['name'].strip(), 'role': match['role'], 'name_evidence': line})
    unique = {}
    for party in parties:
        unique.setdefault((party['name'].casefold(), party['role'].casefold()), party)
    result['parties'] = list(unique.values())
    totals = total_candidates(text)
    if totals:
        candidate = totals[0]
        currencies = [currency for currency, pattern in CURRENCIES.items() if re.search(pattern, candidate['evidence'], re.I)]
        result['total_amount'] = {**candidate, 'currency': currencies[0] if len(currencies) == 1 else None}
    # Use the same evidence/type checks as all LLM paths.
    candidates = result.get('contract_number', {}).pop('candidates', None)
    result = validate_model_result(result, text)
    if candidates:
        result['contract_number']['candidates'] = candidates
    result = assess_fields(result, text, document=document_ir, method='rule')
    for key in ('contract_number', 'contract_date', 'total_amount'):
        result[key]['rule_id'] = f'contract-{key}-v1'
    result['_provenance'] = {'backend': 'rules', 'model': None, 'model_revision': None,
                              'parameters': {}, 'instructions': None, 'template': None}
    return result, {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
