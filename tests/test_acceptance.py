from copy import deepcopy
import pytest

from src.acceptance import score_attributes, metrics
from src.extraction.rules import extract_with_rules


TEXT = '''PAGE 1
ДОГОВОР № 42/26
г. Томск 15.09.2026
Покупатель: ООО "Альфа"
Поставщик: ИП Иванов Иван Иванович
Аванс 1000 рублей. Штраф 200 рублей. НДС 20%.
Общая сумма договора составляет 100 000,50 долларов США.
Приложение к Договору № 777 от 01.01.2020.
'''
GOLD = {'contract_number': '42/26', 'contract_date': '2026-09-15',
        'parties': [{'name': 'ООО "Альфа"', 'role': 'Покупатель'}, {'name': 'ИП Иванов Иван Иванович', 'role': 'Поставщик'}],
        'total_amount': {'value': 100000.5, 'currency': 'USD'}}


def test_rules_do_not_extract_invoice_or_advance_instead_of_agreement():
    fields, usage = extract_with_rules(TEXT)
    assert all(score['correct'] for score in score_attributes(GOLD, fields).values())
    assert all(fields['_quality'][key]['status'] == 'found' for key in GOLD)
    assert usage['total_tokens'] == 0


def test_wrong_currency_or_party_role_fails_the_whole_attribute():
    fields, _ = extract_with_rules(TEXT)
    fields['total_amount']['currency'] = 'RUB'
    fields['parties'][0]['role'] = 'Поставщик'
    scores = score_attributes(GOLD, fields)
    assert not scores['total_amount']['correct']
    assert not scores['parties']['correct']


def test_review_does_not_hide_wrong_values_under_default_precision_policy():
    fields, _ = extract_with_rules(TEXT)
    fields['total_amount'].update(value=5, status='needs_review')
    assert score_attributes(GOLD, fields)['total_amount'] == {'issued': True, 'correct': False, 'expected_present': True}
    assert score_attributes(GOLD, fields, review_policy='abstain')['total_amount']['issued'] is False


def test_one_contract_is_counted_once_and_wrong_format_is_not_ignored():
    fields, _ = extract_with_rules(TEXT)
    good = score_attributes(GOLD, fields)
    bad = deepcopy(good)
    bad['contract_number']['correct'] = False
    result = metrics([{'kind': 'typical', 'files': [{'scores': good}, {'scores': bad}]}])
    assert result['contracts'] == 1
    assert result['typical_all_four_rate'] == 0
    assert result['attributes']['contract_number'] == {'tp': 0, 'fp': 1, 'fn': 1, 'precision': 0, 'recall': 0}


def test_distractor_only_document_abstains():
    fields, _ = extract_with_rules('Счёт № 42 от 15.09.2026.\nАванс 1000 рублей. НДС 200 рублей.')
    assert all(fields['_quality'][key]['status'] == 'not_found' for key in GOLD)


def counted(gold, fields, **kwargs):
    return metrics([{'kind': 'typical', 'files': [{'status': 'ok', 'scores': score_attributes(gold, fields, **kwargs)}]}])


@pytest.mark.parametrize('key', list(GOLD))
def test_correct_absence_is_not_a_false_negative_or_true_positive(key):
    gold = deepcopy(GOLD)
    fields, _ = extract_with_rules(TEXT)
    gold[key] = [] if key == 'parties' else {'value': None, 'currency': None} if key == 'total_amount' else None
    fields[key] = [] if key == 'parties' else {'value': None}
    result = counted(gold, fields)
    assert result['attributes'][key] == {'tp': 0, 'fp': 0, 'fn': 0, 'precision': None, 'recall': None}
    assert result['typical_all_four_rate'] == 1


@pytest.mark.parametrize('key', list(GOLD))
def test_invented_value_with_absent_gold_is_only_a_false_positive(key):
    gold = deepcopy(GOLD)
    fields, _ = extract_with_rules(TEXT)
    gold[key] = [] if key == 'parties' else {'value': None, 'currency': None} if key == 'total_amount' else None
    assert counted(gold, fields)['attributes'][key] == {'tp': 0, 'fp': 1, 'fn': 0, 'precision': 0, 'recall': None}


def test_missing_gold_value_and_incorrect_issued_value_are_distinct():
    fields, _ = extract_with_rules(TEXT)
    fields['total_amount']['value'] = None
    fields['total_amount']['currency'] = None
    assert counted(GOLD, fields)['attributes']['total_amount'] == {'tp': 0, 'fp': 0, 'fn': 1, 'precision': None, 'recall': 0}
    fields['total_amount']['value'] = 5
    assert counted(GOLD, fields)['attributes']['total_amount'] == {'tp': 0, 'fp': 1, 'fn': 1, 'precision': 0, 'recall': 0}


def test_empty_string_is_an_abstention_and_zero_is_an_issued_value():
    fields, _ = extract_with_rules(TEXT)
    fields['total_amount'].update(value='', currency=None)
    assert counted(GOLD, fields)['attributes']['total_amount']['fp'] == 0
    fields['total_amount']['value'] = 0
    assert counted(GOLD, fields)['attributes']['total_amount']['fp'] == 1


def test_abstaining_in_one_format_does_not_make_the_other_correct_answer_false():
    fields, _ = extract_with_rules(TEXT)
    good = score_attributes(GOLD, fields)
    fields['contract_number']['value'] = None
    missing = score_attributes(GOLD, fields)
    result = metrics([{'kind': 'typical', 'files': [{'scores': good}, {'scores': missing}]}])
    assert result['attributes']['contract_number'] == {'tp': 0, 'fp': 0, 'fn': 1, 'precision': None, 'recall': 0}
    assert result['typical_all_four_rate'] == 0


def test_failed_document_with_absent_attributes_cannot_pass_document_metric():
    gold = {'contract_number': None, 'contract_date': None, 'parties': [], 'total_amount': {'value': None, 'currency': None}}
    scores = score_attributes(gold, {})
    result = metrics([{'kind': 'typical', 'files': [{'scores': scores, 'status': 'error'}]}])
    assert result['typical_all_four_rate'] == 0
    assert all(counts['fn'] == 0 for counts in result['attributes'].values())


def test_partial_party_without_role_is_an_error_instead_of_an_evaluator_crash():
    fields, _ = extract_with_rules(TEXT)
    fields['parties'][0]['role'] = None
    assert counted(GOLD, fields)['attributes']['parties']['fp'] == 1


def test_currency_alone_cannot_be_issued_for_an_absent_gold_amount():
    gold = deepcopy(GOLD)
    gold['total_amount'] = {'value': None, 'currency': None}
    fields, _ = extract_with_rules(TEXT)
    fields['total_amount']['value'] = None
    assert counted(gold, fields)['attributes']['total_amount']['fp'] == 1
