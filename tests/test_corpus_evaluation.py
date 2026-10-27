from copy import deepcopy

from src.evaluation import score_legacy, summarize, place

GOLD = {"number": "42", "date": "15.09.2026", "contract_type": "Договор поставки", "place": "г. Москва",
        "term": "31.12.2026", "party1": "ООО Альфа", "party2": "ООО Бета", "inn1": "111", "inn2": "222", "amount": 1000, "vat": "20%"}


def prediction():
    return {"contract_number": {"value": "№ 42"}, "contract_date": {"value": "2026-09-15"}, "contract_type": {"value": "Договор поставки"},
            "place": {"value": "город Москва"}, "term": {"value": "2026-12-31"}, "total_amount": {"value": 1000.0}, "vat": {"rate": 20, "mode": "included"},
            "parties": [{"name": "ООО «Альфа»", "inn": "111"}, {"name": "ООО Бета", "inn": "222"}]}


def test_all_eleven_fields_match_with_format_normalization():
    assert all(score_legacy(GOLD, prediction()).values())


def test_reordering_parties_does_not_change_accuracy():
    fields = prediction()
    fields["parties"].reverse()
    assert all(score_legacy(GOLD, fields).values())


def test_swapped_inns_are_not_accepted_by_set_membership():
    fields = prediction()
    fields["parties"][0]["inn"], fields["parties"][1]["inn"] = "222", "111"
    checks = score_legacy(GOLD, fields)
    assert checks["party1_name"] and checks["party2_name"]
    assert not checks["party1_inn"] and not checks["party2_inn"]


def test_zero_vat_label_does_not_accept_missing_prediction():
    gold = GOLD | {"vat": "0"}
    fields = prediction()
    fields["vat"] = {"rate": None, "mode": None}
    assert score_legacy(gold, fields)["vat"] is False
    fields["vat"]["mode"] = "not_subject"
    assert score_legacy(gold, fields)["vat"] is True


def test_missing_inn_is_scored_instead_of_automatically_passed():
    gold = GOLD | {"inn2": None}
    fields = prediction()
    assert score_legacy(gold, fields)["party2_inn"] is False
    fields["parties"][1]["inn"] = None
    assert score_legacy(gold, fields)["party2_inn"] is True


def test_unparseable_gold_date_does_not_pass_as_none_equals_none():
    fields = prediction()
    fields["term"]["value"] = None
    assert score_legacy(GOLD | {"term": "invalid annotation"}, fields)["term"] is None


def test_summary_counts_failures_but_keeps_unlabeled_files_out_of_accuracy():
    correct = {key: True for key in score_legacy(GOLD, prediction())}
    records = [
        {"document_id": 1, "status": "ok", "field_scores": correct, "extraction_sec": 2},
        {"document_id": 2, "status": "error", "field_scores": {key: False for key in correct}},
        {"document_id": 3, "status": "ok", "field_scores": None, "extraction_sec": 3},
    ]
    result = summarize(records)
    assert result["field_accuracy"] == .5
    assert result["field_accuracy_on_successful_files"] == 1
    assert result["labeled_files"] == 2
    assert result["failed_files"] == 1


def test_city_prefix_does_not_remove_first_letter_of_city():
    assert place("город Москва") == place("г.Москва") == "москва"
    assert place("Горловка") == "горловка"
