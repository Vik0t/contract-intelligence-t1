import json

import pytest
from pydantic import ValidationError

from src.document_ir import DocumentIR, PageIR
from src.parsing import document_ir_to_text
from src.extraction.context import document_chunks
from src.extraction.postprocess import postprocess_extraction
from src.extraction.validation import validate_model_result, merge_extractions
from src.extraction import risks, summary


def test_empty_pages_cannot_be_analyzed_as_page_markers():
    document = DocumentIR(source_format="pdf", source_path="empty.pdf", page_count=1, pages=[PageIR(number=1)])
    with pytest.raises(ValueError, match="не содержит текста"):
        document_ir_to_text(document)


def test_chunking_keeps_tail_and_repeats_correct_page_markers():
    text = "PAGE 1\n" + "начало " * 120 + "\nPAGE 7\n" + "условие " * 170 + "КОНЕЦ ДОГОВОРА"
    chunks = document_chunks(text, 512, overlap=50)
    assert len(chunks) > 2
    assert all(len(chunk) <= 512 for chunk in chunks)
    assert "КОНЕЦ ДОГОВОРА" in chunks[-1]
    assert chunks[-1].startswith("PAGE 7")


def test_signature_date_is_not_fabricated_as_contract_end():
    result = postprocess_extraction({"term": {"value": None}}, "Договор заключён 15.09.2026.")
    assert result["term"]["value"] is None


def test_contract_type_is_not_overwritten_by_incidental_insurance_clause():
    result = postprocess_extraction({"contract_type": {"value": "Договор поставки"}}, "Поставщик страхует имущество от повреждений.")
    assert result["contract_type"]["value"] == "Договор поставки"


def test_unfounded_extraction_is_cleared_and_wrong_page_is_repaired():
    result = validate_model_result({
        "contract_number": {"value": "42", "evidence": "Договор № 42", "page_number": 99},
        "total_amount": {"value": 100000, "evidence": "Цена 100000 рублей"},
    }, "PAGE 3\nДоговор № 42")
    assert result["contract_number"]["page_number"] == 3
    assert result["total_amount"]["value"] is None
    assert result["term"]["value"] is None


@pytest.mark.parametrize("payload", [
    {"total_amount": {"value": True}},
    {"contract_date": {"value": []}},
    {"parties": "Альфа"},
])
def test_malformed_model_output_cannot_be_persisted(payload):
    with pytest.raises(ValidationError):
        validate_model_result(payload, "PAGE 1\nДоговор")


def test_chunk_merge_preserves_zero_amount_and_fills_later_party_inn():
    first = validate_model_result({"total_amount": {"value": 0, "evidence": "Безвозмездно"}, "parties": [{"name": "Альфа", "name_evidence": "Альфа"}]}, "PAGE 1\nАльфа. Безвозмездно")
    second = validate_model_result({"total_amount": {"value": 10, "evidence": "Цена 10"}, "parties": [{"name": "Альфа", "name_evidence": "Альфа", "inn": "123", "inn_evidence": "ИНН 123"}]}, "PAGE 2\nАльфа. ИНН 123. Цена 10")
    result = merge_extractions([first, second])
    assert result["total_amount"]["value"] == 0
    assert len(result["parties"]) == 1
    assert result["parties"][0]["inn"] == "123"


def test_chunk_merge_preserves_main_contract_vat_without_raw_value():
    first = validate_model_result({"vat": {"rate": 0, "mode": "not_subject", "evidence": "НДС не облагается"}}, "PAGE 1\nНДС не облагается")
    appendix = validate_model_result({"vat": {"rate": 20, "mode": "included", "evidence": "включая НДС 20%"}}, "PAGE 8\nвключая НДС 20%")
    assert merge_extractions([first, appendix])["vat"] == first["vat"]


def test_local_summary_and_risks_never_call_cloud(monkeypatch):
    monkeypatch.setenv("SUMMARY_BACKEND", "local")
    monkeypatch.setenv("RISK_BACKEND", "local")
    monkeypatch.setenv("ML_ALLOW_EXTERNAL", "false")
    monkeypatch.setattr(summary, "_get_client", lambda: pytest.fail("External call attempted"))
    monkeypatch.setattr(summary, "_summarize_local", lambda prompt, *_args: "[]" if "JSON-массив" in prompt else "Договор поставки.")
    assert summary.summarize_document("PAGE 1\nДоговор поставки", {}) == "Договор поставки."
    assert risks.analyze_risks("PAGE 1\nДоговор поставки", {}) == []
    with pytest.raises(RuntimeError, match="Внешний анализ отключён"):
        summary.generate_chat("данные", model="x", max_tokens=1, provider="hf")


def test_risks_read_late_pages_and_repair_evidence_page(monkeypatch):
    monkeypatch.setenv("RISK_MAX_INPUT_CHARS", "512")
    seen = []
    evidence = "Поставщик вправе увеличить цену без согласия Покупателя."

    def generate(prompt, **kwargs):
        seen.append(prompt)
        data = [{"title": "Изменение цены", "body": "Для Покупателя цена не ограничена.", "evidence": evidence, "page": 1}] if evidence in prompt else []
        return kwargs["parse"](json.dumps(data, ensure_ascii=False))

    monkeypatch.setattr(risks, "generate_with_fallback", generate)
    result = risks.analyze_risks("PAGE 1\n" + "Обычные условия. " * 100 + "\nPAGE 9\n" + evidence, {})
    assert len(seen) > 1
    assert result[0]["page"] == 9


def test_summary_reads_tail_before_reduction(monkeypatch):
    monkeypatch.setenv("SUMMARY_BACKEND", "local")
    prompts = []

    def generate(prompt, *_args):
        prompts.append(prompt)
        return "Краткое содержание фрагмента."

    monkeypatch.setattr(summary, "_summarize_local", generate)
    result = summary.summarize_document("PAGE 1\n" + "условие " * 200 + "\nPAGE 4\nПОСЛЕДНЕЕ УСЛОВИЕ", {}, max_input_chars=512)
    assert result
    assert any("ПОСЛЕДНЕЕ УСЛОВИЕ" in prompt for prompt in prompts)
    assert "Заметки по фрагментам" in prompts[-1]


def test_model_cannot_bypass_currency_grounding_by_claiming_manual_method():
    from src.extraction.validation import validate_model_result
    result = validate_model_result({'total_amount': {'value': 1200, 'currency': 'USD',
        'evidence': 'Общая сумма договора 1200.', 'method': 'manual'}},
        'Общая сумма договора 1200.')
    assert result['total_amount']['currency'] is None
    assert result['total_amount']['method'] != 'manual'
