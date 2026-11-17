from copy import deepcopy

import pytest

from src.extraction.header_fields import recover_header_fields
from src.extraction.party_resolution import canonical_legal_name, identity, name_spans, merge_parties


def test_signing_place_over_party_address_preserves_the_rejected_candidate():
    text = 'PAGE 1\nМесто подписания: Дата подписания:\nг. Томск 08 июня 2031 года\nДоговор № Т-54\n1. Предмет договора.\nЮридический адрес: г. Омск.'
    value = {'place': {'value': 'г. Омск', 'evidence': 'Юридический адрес: г. Омск.'}}
    item = recover_header_fields(value, text)['place']
    assert item['value'] == 'Томск' and item['method'] == 'rule'
    assert item['status'] == 'needs_review'
    assert item['source_correction']['previous_value'] == 'г. Омск'
    assert item['evidence'] in text


def test_city_embedded_in_the_ocr_heading_is_not_a_warehouse_address():
    text = 'PAGE 1\nДОГОВОР № Т-54 г. Иркутск 8 июня 2031 года\nООО «Пример», именуемое Заказчиком.\nАдрес склада: г. Иркутск, улица Лесная, 5.'
    value = {'place': {'value': 'г. Иркутск, улица Лесная, 5', 'evidence': 'Адрес склада: г. Иркутск, улица Лесная, 5.'}}
    item = recover_header_fields(value, text)['place']
    assert item['value'] == 'Иркутск'
    assert item['source_correction']['previous_value'].endswith('Лесная, 5')


@pytest.mark.parametrize('quote', ['Подписано в г. Омск.', 'Место подписания: г. Омск, юридический адрес: г. Томск.'])
def test_explicit_signing_evidence_is_not_replaced_as_an_address(quote):
    value = {'place': {'value': 'г. Омск', 'evidence': quote}}
    before = deepcopy(value)
    assert recover_header_fields(value, 'PAGE 1\nМесто подписания: г. Томск\nДоговор № Т-54\n1. Предмет.\n' + quote) == before


def test_two_header_cities_are_not_resolved_by_guessing():
    value = {'place': {'value': 'г. Омск', 'evidence': 'Юридический адрес: г. Омск.'}}
    text = 'PAGE 1\nМесто подписания: г. Томск\nМесто подписания: г. Иркутск\nДоговор № Т-54\n1. Предмет.'
    assert recover_header_fields(value, text)['place']['value'] == 'г. Омск'


@pytest.mark.parametrize('raw, canonical', [('000 «Нива»', 'ООО «Нива»'), ('O00 «Нива»', 'ООО «Нива»'),
    ('OOO «Нива»', 'ООО «Нива»'), ('AO «Нива»', 'АО «Нива»'), ('A0 «Нива»', 'АО «Нива»'),
    ('Акционерное — общество «Нива»', 'Акционерное общество «Нива»')])
def test_only_the_legal_form_is_repaired_and_the_source_is_retained(raw, canonical):
    assert canonical_legal_name(raw) == canonical
    assert identity(raw) == identity(canonical)
    assert name_spans(canonical, raw)
    result = merge_parties([], [{'name': raw, 'name_evidence': raw}])[0]
    assert result['name'] == canonical and result['name_evidence'] == raw
    assert result['name_source_variants'][0]['name'] == raw


@pytest.mark.parametrize('value', ['000 Нива', '1000 «Нива»', 'ООО «000 Нива»', 'ООО «Нива — Юг»'])
def test_digits_and_punctuation_inside_the_company_name_are_preserved(value):
    assert canonical_legal_name(value) == value


def test_company_identity_and_conflicting_tax_ids_are_not_collapsed():
    assert len(merge_parties([{'name': 'ООО «Нива»', 'inn': '1234567890'}],
                           [{'name': '000 «Другая»', 'inn': '1234567890'}])) == 2
    assert len(merge_parties([{'name': 'ООО «Нива»', 'inn': '1234567890'}],
                           [{'name': '000 «Нива»', 'inn': '9876543210'}])) == 2
    same = merge_parties([{'name': 'ООО «Нива»', 'inn': None}],
                         [{'name': '000 «Нива»', 'inn': '1234567890', 'inn_evidence': 'ИНН 1234567890'}])
    assert len(same) == 1 and same[0]['inn'] == '1234567890'
    assert same[0]['inn_evidence'] == 'ИНН 1234567890'
