"""Synthetic invariants: layout and unrelated clauses must not change facts."""
from copy import deepcopy

import pytest

from src.extraction.postprocess import postprocess_extraction
from src.extraction.context import evidence_pages


@pytest.mark.parametrize("separator", [" ", "\n", "\n\n", "\u00a0", "\n    "])
@pytest.mark.parametrize("date_text, expected", [("19.02.2031", "2031-02-19"), ("19 февраля 2031 года", "2031-02-19")])
def test_contract_end_is_invariant_to_layout(separator, date_text, expected):
    text = f"PAGE 6\nДоговор действует до{separator}{date_text}."
    result = postprocess_extraction({"term": {"value": None}}, text)
    assert result["term"]["value"] == expected
    assert evidence_pages(text, result["term"]["evidence"]) == [6]


def test_loan_repayment_cue_survives_line_wrapping():
    result = postprocess_extraction({"term": {"value": None}},
        "PAGE 3\nЗаемщик обязуется возвратить всю сумму займа в полном\n\nобъеме до 21 сентября 2032 года.")
    assert result["term"]["value"] == "2032-09-21"
    assert result["term"]["semantic_type"] == "loan_repayment_date"


@pytest.mark.parametrize("text", [
    "Оплата до 19.02.2031. Договор действует до полного исполнения обязательств.",
    "Подписан 19.02.2031. Срок действия определяется соглашением сторон.",
    "Срок гарантии до 19.02.2031. Договор действует до полного исполнения обязательств.",
])
def test_end_cue_cannot_be_borrowed_from_next_clause(text):
    assert postprocess_extraction({"term": {"value": None}}, text)["term"]["value"] is None


def test_term_evidence_does_not_cross_page_markers():
    text = "PAGE 4\nДоговор действует до 19.02.2031.\nPAGE 5\nАдреса и реквизиты сторон."
    item = postprocess_extraction({"term": {"value": None}}, text)["term"]
    assert "PAGE" not in item["evidence"]
    assert evidence_pages(text, item["evidence"]) == [4]


def test_surviving_warranty_obligations_do_not_remove_explicit_contract_end():
    text = "Договор действует до 19.02.2031, а в части гарантийных обязательств — до полного исполнения."
    assert postprocess_extraction({"term": {"value": None}}, text)["term"]["value"] == "2031-02-19"


@pytest.mark.parametrize("party", ["Образовательная организация", "Страховая компания", "Транспортная компания"])
def test_explicit_heading_beats_incidental_party_business(party):
    text = f"PAGE 1\nДОГОВОР ОКАЗАНИЯ УСЛУГ № А-1\n{party}: ООО «Пример».\nПредмет: консультационные услуги."
    item = postprocess_extraction({"contract_type": {"value": "Договор страхования имущества"}}, text)["contract_type"]
    assert item["value"] == "Договор возмездного оказания услуг"
    assert item["evidence"] == "ДОГОВОР ОКАЗАНИЯ УСЛУГ № А-1"


def test_wrapped_heading_preserves_explicit_type():
    text = "PAGE 1\nДОГОВОР\nПЕРЕВОЗКИ № Б-2\nЭкспедитор также оказывает дополнительные услуги."
    item = postprocess_extraction({"contract_type": {"value": None}}, text)["contract_type"]
    assert item["value"] == "Договор перевозки"
    assert evidence_pages(text, item["evidence"]) == [1]


def test_unnamed_contract_is_not_classified_from_party_or_appendix_title():
    text = "PAGE 1\nДОГОВОР № В-3\nОбразовательная организация: ООО «Пример».\nPAGE 2\nДОГОВОР СТРАХОВАНИЯ"
    item = postprocess_extraction({"contract_type": {"value": None}}, text)["contract_type"]
    assert item["value"] is None


def test_inline_clause_does_not_override_named_heading():
    item = postprocess_extraction({"contract_type": {"value": None}},
        "Договор поставки. Поставщик обеспечивает страхование имущества.")["contract_type"]
    assert item["value"] == "Договор поставки"


@pytest.mark.parametrize("evidence", ["Заем беспроцентный.", "Исполнитель применяет УСН.", "Проценты не начисляются."])
def test_vat_exemption_is_not_inferred_from_unrelated_tax_or_loan_fact(evidence):
    item = postprocess_extraction({"vat": {"mode": "not_subject", "rate": 0, "evidence": evidence}}, evidence)["vat"]
    assert item["mode"] is None and item["rate"] is None


@pytest.mark.parametrize("evidence", ["Цена без НДС.", "НДС не облагается.", "Освобожден от налога на добавленную стоимость."])
def test_explicit_vat_statement_is_preserved(evidence):
    original = {"vat": {"mode": "not_subject", "rate": None, "evidence": evidence}}
    assert postprocess_extraction(deepcopy(original), evidence) == original


def test_vat_citation_can_be_repaired_only_from_verbatim_raw_statement():
    text = "PAGE 2\nЦена договора 700 рублей.\nPAGE 3\nНДС не облагается."
    original = {"vat": {"mode": "not_subject", "raw_value": "НДС не облагается", "evidence": "Цена договора 700 рублей.", "page_number": 2}}
    item = postprocess_extraction(original, text)["vat"]
    assert item["evidence"] == "НДС не облагается" and item["page_number"] == 3
    fabricated = {"vat": {"mode": "not_subject", "raw_value": "Без НДС", "evidence": "Цена договора 700 рублей."}}
    assert postprocess_extraction(fabricated, text)["vat"]["mode"] is None
