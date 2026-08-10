from src.local_extraction import postprocess_extraction


def test_postprocess_canonicalizes_contract_type_and_word_date() -> None:
    result = {
        "contract_type": {
            "value": "Договор перевозок",
            "evidence": "ДОГОВОР № 479-76-2024 (перевозки)",
        },
        "term": {
            "value": "до 06 декабря 2026 года включительно",
            "semantic_type": "contract_end_date",
            "evidence": "в срок до 06 декабря 2026 года включительно",
        },
    }

    processed = postprocess_extraction(
        result,
        "ДОГОВОР № 479-76-2024 (перевозки). "
        "Договор действует до 06 декабря 2026 года включительно.",
    )

    assert processed["contract_type"]["value"] == "Договор перевозки"
    assert processed["contract_type"]["raw_value"] == "Договор перевозок"
    assert processed["term"]["value"] == "2026-12-06"
    assert processed["term"]["semantic_type"] == "contract_end_date"


def test_postprocess_prefers_loan_repayment_date_over_payment_date() -> None:
    result = {
        "term": {
            "value": "до 01.05.2026",
            "semantic_type": "contract_end_date",
            "evidence": "Срок оплаты процентов — до 01.05.2026.",
        }
    }

    processed = postprocess_extraction(
        result,
        "Срок оплаты процентов — до 01.05.2026. "
        "Заемщик обязан возвратить сумму займа до 18.11.2026.",
    )

    assert processed["term"]["value"] == "2026-11-18"
    assert processed["term"]["semantic_type"] == "loan_repayment_date"


def test_postprocess_selects_end_of_service_interval() -> None:
    result = {
        "term": {
            "value": "01.09.2026",
            "semantic_type": "contract_end_date",
            "evidence": "с 01.09.2026 по 30.09.2026",
        }
    }

    processed = postprocess_extraction(
        result,
        "Период оказания услуг: с 01.09.2026 по 30.09.2026.",
    )

    assert processed["term"]["value"] == "2026-09-30"
    assert processed["term"]["semantic_type"] == "service_period_end_date"
