import pytest

from src.extraction.grounding import source_quote
from src.extraction.source_context import informative_subject_evidence
from src.extraction.validation import validate_model_result


@pytest.mark.parametrize('word, quote', [('кабельно-\n\nпроводниковой', 'кабельно-проводниковой'),
                                       ('лаборатор-\nного', 'лабораторного')])
def test_typographic_wrap_restores_the_original_contiguous_quote(word, quote):
    text = f'PAGE 2\nПоставщик обязуется передать комплект {word} продукции.'
    evidence = f'Поставщик обязуется передать комплект {quote} продукции.'
    restored = source_quote(text, evidence)
    assert restored in text and word in restored
    item = validate_model_result({'contract_type': {'value': 'Договор поставки', 'evidence': evidence}}, text)['contract_type']
    assert item['value'] == 'Договор поставки' and item['page_number'] == 2
    assert item['evidence'] == restored


@pytest.mark.parametrize('quote', ['Цена 1234 рублей.', 'Поставщик обязан передать товар.',
                                  'Передать товары покупателю.'])
def test_word_changes_and_digits_do_not_get_fuzzy_matched(quote):
    text = 'Цена 123-\n4 рублей. Поставщик обязуется передать то-\nвар покупателю.'
    assert source_quote(text, quote) is None


def test_named_scope_in_general_provisions_is_valid_but_a_heading_is_not():
    quote = 'Настоящий Договор регулирует отношения Сторон, связанные с поставкой оборудования.'
    text = 'PAGE 1\n1. ОБЩИЕ ПОЛОЖЕНИЯ\n1.1. ' + quote + '\n2. ПРЕДМЕТ ДОГОВОРА\n2.1. Условия согласуются.'
    assert informative_subject_evidence(text, quote)
    assert not informative_subject_evidence(text, 'ПРЕДМЕТ ДОГОВОРА')
    assert not informative_subject_evidence('ПРИЛОЖЕНИЕ\n' + text, quote)
