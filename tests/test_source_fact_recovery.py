from copy import deepcopy

import pytest

from src.extraction.context import evidence_pages
from src.extraction.postprocess import postprocess_extraction
from src.extraction.source_facts import recover_explicit_facts
from src.extraction.validation import ContractResult, merge_extractions


def empty_result():
    return ContractResult().model_dump()


@pytest.mark.parametrize('label', ['Общая стоимость Работ по настоящему Договору',
                                  'Стоимость услуг по настоящему Договору', 'Цена договора'])
def test_missing_total_comes_from_explicit_contract_price(label):
    text = f'PAGE 3\n{label} составляет 731 205 рублей.\nАванс — 100 рублей.'
    result = merge_extractions([empty_result()], text)
    amount = result['total_amount']
    assert amount['value'] == 731205
    assert amount['method'] == 'rule'
    assert evidence_pages(text, amount['evidence']) == [3]


@pytest.mark.parametrize('text', [
    'Оклад составляет 90 000 рублей в месяц.',
    'Стоимость услуг по договору составляет 9000 рублей в месяц.',
    'Аванс составляет 500 рублей. Штраф — 700 рублей.',
    'Договор без суммы.\nПРИЛОЖЕНИЕ № 1\nЦена договора составляет 999 рублей.',
])
def test_periodic_payments_and_appendix_totals_are_not_recovered(text):
    result = recover_explicit_facts(empty_result(), text)
    assert result['total_amount']['value'] is None


def test_conflicting_totals_are_exposed_instead_of_choosing_one():
    text = 'Цена договора: 1200 рублей.\nЦена договора: 2400 рублей.'
    amount = merge_extractions([empty_result()], text)['total_amount']
    assert amount['value'] is None and amount['status'] == 'needs_review'
    assert {c['value'] for c in amount['candidates']} == {1200, 2400}


@pytest.mark.parametrize('quote', ['НДС не облагается', 'не облагается налогом на добавленную стоимость',
                                  'Исполнитель освобожден от уплаты налога на добавленную стоимость (НДС)'])
def test_explicit_missing_vat_is_recovered_with_verbatim_source(quote):
    text = 'PAGE 4\n' + quote + '.'
    vat = merge_extractions([empty_result()], text)['vat']
    assert vat['mode'] == 'not_subject' and vat['rate'] is None
    assert vat['evidence'] in text and vat['page_number'] == 4


@pytest.mark.parametrize('text', ['Применяется УСН.', 'Процентная ставка 0%.', 'Без НДС.',
    'НДС по ставке 0%.', 'ПРИЛОЖЕНИЕ № 1\nНДС не облагается.'])
def test_no_vat_exemption_is_inferred_from_another_fact(text):
    vat = recover_explicit_facts(empty_result(), text)['vat']
    assert vat['mode'] is None and vat['rate'] is None


def test_mixed_vat_requires_review_and_does_not_become_exemption():
    vat = merge_extractions([empty_result()], 'НДС не облагается. Другая часть включает НДС 20%.')['vat']
    assert vat['mode'] is None and vat['status'] == 'needs_review'


@pytest.mark.parametrize('text', [
    'Если Исполнитель освобожден от уплаты НДС, расчёты производятся без налога.',
    'Исполнитель не освобожден от уплаты налога на добавленную стоимость.',
    'НДС не облагается при условии подтверждения льготы.',
    'Исполнитель может быть освобожден от уплаты НДС.',
])
def test_conditional_and_negated_exemptions_do_not_become_facts(text):
    vat = recover_explicit_facts(empty_result(), text)['vat']
    assert vat['mode'] is None and vat['rate'] is None


def test_recovery_preserves_existing_model_values():
    original = empty_result()
    original['total_amount'].update(value=500, evidence='Стоимость: 500 рублей.')
    original['vat'].update(mode='included', rate=20, evidence='Включая НДС 20%.')
    result = recover_explicit_facts(deepcopy(original), 'Цена договора: 1000 рублей. НДС не облагается.')
    assert result == original


def test_work_deadline_is_not_presented_as_contract_expiration():
    text = ('PAGE 2\nСрок выполнения Работ: с даты подписания до 16\nиюня 2032 года.\n'
            'Договор действует до полного исполнения обязательств.')
    term = merge_extractions([empty_result()], text)['term']
    assert term['value'] == '2032-06-16'
    assert term['semantic_type'] == 'work_completion_date'
    assert evidence_pages(text, term['evidence']) == [2]


def test_calendar_expiry_has_priority_over_a_work_deadline():
    text = 'Срок выполнения работ до 16 июня 2032 года. Договор действует до 30 сентября 2032 года.'
    term = postprocess_extraction({'term': {'value': None}}, text)['term']
    assert term['value'] == '2032-09-30' and term['semantic_type'] == 'contract_end_date'
