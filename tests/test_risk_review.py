import json
import pytest
from pydantic import ValidationError
from src.extraction import risk_review as review
from src.extraction.risk_catalog import applicable_rules, RULES

CUSTOMER = dict(contract_type='supply', user_side='customer', scope_confirmed=True)


def assessment(profile=CUSTOMER, **changes):
    checks = [dict(rule_id=rule['id'], status='not_found', evidence_ids=[], related_clause_ids=[], body='') for rule in applicable_rules(review.RiskProfile(**profile))]
    for check in checks:
        check.update(changes.get(check['rule_id'], {}))
    return dict(scope='supported', scope_reason='', checks=checks)


def mock_model(monkeypatch, decide, quotes=()):
    prompts = []
    def generate(prompt, **kwargs):
        prompts.append(prompt)
        if 'ЭТАП: СБОР УСЛОВИЙ' in prompt:
            text = prompt.split('Текст фрагмента:\n', 1)[1]
            output = dict(complete=True, clauses=[dict(evidence=quote, page=None) for quote in quotes if quote in text])
        else:
            output = decide(prompt)
        return kwargs['parse'](json.dumps(output, ensure_ascii=False))
    monkeypatch.setattr(review, 'generate_with_fallback', generate)
    return prompts


def test_far_away_general_limit_is_reconciled_with_penalty(monkeypatch):
    penalty = 'Покупатель уплачивает неустойку 3% от цены за день просрочки.'
    cap = 'Общая ответственность Покупателя, включая неустойку, ограничена 10% цены.'
    monkeypatch.setenv('RISK_REVIEW_CHUNK_CHARS', '512')
    def decide(prompt):
        assert penalty in prompt and cap in prompt
        return assessment(uncapped_penalty=dict(status='mitigated', evidence_ids=['c2'], related_clause_ids=['c1'], body='Общий предел распространяется на неустойку.'))
    prompts = mock_model(monkeypatch, decide, (penalty, cap))
    text = 'PAGE 1\n' + penalty + '\n' + 'Обычные условия. ' * 200 + '\nPAGE 9\n' + cap
    result = review.review_contract_risks(text, {}, CUSTOMER)
    assert result['findings'] == []
    assert result['coverage']['chunks_scanned'] == len(prompts) - 1 > 2
    check = next(item for item in result['checks'] if item['rule_id'] == 'uncapped_penalty')
    assert check['evidence'][0]['page'] == 9
    assert check['related_clauses'][0]['page'] == 1


def test_risk_basis_cannot_be_invented_by_model(monkeypatch):
    quote = 'Поставщик вправе увеличивать цену без согласия Покупателя.'
    mock_model(monkeypatch, lambda _: assessment(price_change=dict(status='risk', evidence_ids=['c1'], body='Покупатель может заплатить больше согласованной цены.')), (quote,))
    report = review.review_contract_risks('PAGE 2\n' + quote, {}, CUSTOMER)
    risk = report['findings'][0]
    assert risk['rule_id'] == 'price_change'
    assert risk['page'] == 2
    assert risk['affected_side'] == 'customer'
    assert risk['basis']['legal_references'][0]['articles'] == 'ст. 310, 424, 450.1'
    assert risk['recommendation']
    assert report['source_sha256'] and report['catalog_version']


def test_provider_cannot_receive_buyers_price_increase_risk(monkeypatch):
    profile = {**CUSTOMER, 'user_side': 'provider'}
    def decide(prompt):
        assert 'price_change' not in prompt.split('Правила:', 1)[1]
        return assessment(profile)
    mock_model(monkeypatch, decide)
    assert review.review_contract_risks('PAGE 1\nДоговор поставки, обычные условия.', {}, profile)['findings'] == []
    customer_ids = {r['id'] for r in applicable_rules(review.RiskProfile(**CUSTOMER))}
    provider_ids = {r['id'] for r in applicable_rules(review.RiskProfile(**profile))}
    assert 'payment_dependency' in provider_ids - customer_ids


def test_services_rules_are_not_applied_to_supply():
    supply = {r['id'] for r in applicable_rules(review.RiskProfile(**CUSTOMER))}
    services = {r['id'] for r in applicable_rules(review.RiskProfile(**{**CUSTOMER, 'contract_type': 'services'}))}
    assert 'services_customer_exit' in services - supply
    assert 'advance_retention' in supply - services
    assert len(RULES) == 12


@pytest.mark.parametrize('change', [
    dict(evidence_ids=['invented']),
    dict(evidence_ids=[]),
    dict(body='Условие ничтожно по статье 999 ГК РФ'),
])
def test_invalid_final_proof_fails_closed(monkeypatch, change):
    quote = 'Поставщик вправе увеличивать цену без согласия Покупателя.'
    value = dict(status='risk', evidence_ids=['c1'], body='Цена может увеличиться.')
    value.update(change)
    mock_model(monkeypatch, lambda _: assessment(price_change=value), (quote,))
    with pytest.raises(ValueError):
        review.review_contract_risks('PAGE 1\n' + quote, {}, CUSTOMER)


def test_one_missed_rule_rejects_apparently_successful_empty_answer(monkeypatch):
    output = assessment()
    output['checks'].pop()
    mock_model(monkeypatch, lambda _: output)
    with pytest.raises(ValueError, match='Не все проверки'):
        review.review_contract_risks('PAGE 1\nОбычный договор поставки.', {}, CUSTOMER)


def test_ungrounded_passage_cannot_enter_global_review(monkeypatch):
    def generate(prompt, **kwargs):
        return kwargs['parse'](json.dumps(dict(complete=True, clauses=[dict(evidence='Такого условия не существует', page=5)])))
    monkeypatch.setattr(review, 'generate_with_fallback', generate)
    with pytest.raises(ValueError, match='Неподтверждённая'):
        review.review_contract_risks('PAGE 1\nОбычный договор поставки.', {}, CUSTOMER)


def test_context_overflow_never_truncates_remaining_protective_clauses(monkeypatch):
    quote = 'Ответственность ограничена ценой договора.'
    monkeypatch.setenv('RISK_REVIEW_GLOBAL_CHARS', '5')
    mock_model(monkeypatch, lambda _: pytest.fail('Must not assess an incomplete ledger'), (quote,))
    with pytest.raises(review.ReviewIncomplete):
        review.review_contract_risks('PAGE 1\n' + quote, {}, CUSTOMER)


@pytest.mark.parametrize('text', ['Закупка по 44-ФЗ', 'Договор по 223 – ФЗ', 'Защита прав потребителей'])
def test_special_regime_is_not_silently_treated_as_b2b(monkeypatch, text):
    monkeypatch.setattr(review, 'generate_with_fallback', lambda *_a, **_k: pytest.fail('No model call'))
    with pytest.raises(review.ScopeNotSupported):
        review.review_contract_risks(text, {}, CUSTOMER)


def test_user_must_explicitly_select_side_and_confirm_scope():
    for profile in ({}, {**CUSTOMER, 'user_side': ''}, {**CUSTOMER, 'scope_confirmed': False}, {**CUSTOMER, 'jurisdiction': 'US'}):
        with pytest.raises(ValidationError):
            review.RiskProfile.model_validate(profile)


def test_missing_appendix_is_a_question_not_fabricated_risk(monkeypatch):
    quote = 'Лимиты ответственности установлены в Приложении № 2.'
    mock_model(monkeypatch, lambda _: assessment(uncapped_penalty=dict(status='needs_context', evidence_ids=['c1'], body='Нужно приложение № 2 для определения предела.')), (quote,))
    result = review.review_contract_risks('PAGE 1\n' + quote, {}, CUSTOMER)
    assert not result['findings']
    assert any(item['status'] == 'needs_context' for item in result['checks'])


def test_valid_scope_rejection_does_not_retry_or_switch_provider(monkeypatch):
    prompts = mock_model(monkeypatch, lambda _: {'scope': 'outside_scope', 'scope_reason': 'Применяется иностранное право.', 'checks': []})
    with pytest.raises(review.ScopeNotSupported, match='иностранное право'):
        review.review_contract_risks('PAGE 1\nДоговор поставки.', {}, CUSTOMER)
    assert len(prompts) == 2  # One scan and one valid final decision, not a retry.
