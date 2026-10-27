"""Generated source layouts and negative cases, independent of corpus labels."""
from copy import deepcopy
import json

import pytest

from src.extraction.header_fields import recover_header_fields
from src.extraction.party_resolution import link_from_source, source_links
from src.extraction.postprocess import postprocess_extraction
from src.extraction.source_context import header_region, subject_region
from src.extraction.validation import validate_model_result, merge_extractions
from src.extraction.validation import ContractResult
from src.extraction.recovery import recover_missing


@pytest.mark.parametrize('name,role,inn', [
    ('Орлов Артём Павлович','Доверитель','120000000001'),
    ('ООО «Вектор-Запад»','Заказчик','1200000002'),
])
def test_role_record_can_contain_identity_fields_before_inn(name,role,inn):
    text=f'PAGE 1\n{role}: \n{name}\nПаспорт: серия 4321 номер 654321\nСНИЛС: 111-222-333 44\nИНН: {inn}\nКонтрагент:\nДругое лицо\nИНН: 9900000000'
    result,issues=link_from_source([{'name':name,'role':role,'inn':None},
                                  {'name':None,'inn':inn,'inn_evidence':f'ИНН: {inn}'}],text)
    assert len(result)==1 and result[0]['inn']==inn and not issues
    assert name in result[0]['inn_link']['evidence']


@pytest.mark.parametrize('middle', [
    'Банк: ПАО «Другой банк»',
    'Представитель: Другое лицо',
    'Счёт: 40700000000000000000',
    'Другая сторона:\nДругое лицо',
])
def test_role_record_does_not_borrow_inn_after_foreign_identity_or_bank(middle):
    rows=[{'name':'Орлов Артём Павлович','role':'Заказчик','inn':None}]
    text=f'Заказчик:\nОрлов Артём Павлович\n{middle}\nИНН: 9900000000'
    assert not source_links(rows,text)


def test_record_with_conflicting_tax_ids_is_not_resolved():
    rows=[{'name':'Орлов Артём Павлович','role':'Заказчик','inn':None}]
    text='Заказчик:\nОрлов Артём Павлович\nПаспорт: серия 4321 номер 654321\nИНН: 120000000001\nИНН: 120000000002'
    assert not source_links(rows,text)


@pytest.mark.parametrize('date,expected', [('08.09.2035','2035-09-08'),('«08» сентября 2035 года','2035-09-08')])
@pytest.mark.parametrize('city', ['Тверь','Нижний Новгород','Санкт-Петербург'])
def test_combined_header_labels_and_separate_values(date,expected,city):
    text=f'PAGE 1\nДоговор № QA-X\nМесто подписания: Дата подписания:\nг. {city} {date}\n1. Предмет договора\nОплата до 01.01.2036.'
    fields={'contract_date':{'value':None},'place':{'value':None}}
    result=recover_header_fields(fields,text)
    assert result['contract_date']['value']==expected and result['place']['value']==city
    assert result['contract_date']['evidence']==f'г. {city} {date}'


def test_conventional_city_and_date_on_two_lines():
    text='PAGE 1\nДоговор № QA-X\nг. Тверь\n08 сентября 2035 года\n1. Предмет договора'
    result=recover_header_fields({'contract_date':{},'place':{}},text)
    assert result['contract_date']['value']=='2035-09-08' and result['place']['value']=='Тверь'


def test_full_signing_labels_use_same_header_boundary_policy():
    text='PAGE 1\nДоговор №QA-X\nМесто заключения договора: г. Тверь\nДата подписания договора: 08.09.2035'
    fields=recover_header_fields({'place':{},'contract_date':{}},text)
    assert fields['place']['value']=='Тверь' and fields['contract_date']['value']=='2035-09-08'


@pytest.mark.parametrize('body', [
    '1. Предмет договора\nАдрес: г. Тверь. Дата оплаты: 08.09.2035.',
    'Физическое лицо Орлов Артём Павлович, паспорт выдан 08.09.2035 в г. Тверь.',
    'ИНН 120000000001\nАдрес: г. Тверь\n08.09.2035',
    'Заказчик: Некоторое лицо\nг. Тверь\n08.09.2035',
    'Место подписания: Дата подписания:\nДоговор № 08.09.2035',
    'Счёт № QA-X\nДата договора: 08.09.2035\nМесто подписания: г. Тверь',
    'Приложение №1\nДата подписания: 08.09.2035\nМесто подписания: г. Тверь',
])
def test_signing_values_are_not_inferred_from_other_dates_or_addresses(body):
    result=recover_header_fields({'contract_date':{},'place':{}},'PAGE 1\n'+body)
    assert result['contract_date'].get('value') is None and result['place'].get('value') is None


def test_conflicting_signing_dates_remain_candidates_and_filled_fields_are_preserved():
    text='Дата подписания: 08.09.2035\nДата подписания: 09.09.2035'
    result=recover_header_fields({'contract_date':{}},text)
    assert result['contract_date'].get('value') is None
    assert result['contract_date']['status']=='needs_review'
    fields={'contract_date':{'value':'2034-01-01'}};before=deepcopy(fields)
    assert recover_header_fields(fields,text)==before


def test_appendix_header_is_not_used_as_agreement_header():
    fields={'contract_date':{},'place':{}}
    assert recover_header_fields(fields,'PAGE 4\nг. Тверь 08.09.2035')==fields


def test_ocr_merged_header_still_identifies_explicit_title():
    text='PAGE 1\nг. Тверь 08.09.2035 Номер договора: QA-X ДОГОВОР ПЕРЕВОЗКИ РЕКВИЗИТЫ СТОРОН:\nЭкспедитор: ООО «Пример»'
    result=postprocess_extraction({'contract_type':{'value':'Договор транспортно-экспедиционного обслуживания'}},text)
    assert result['contract_type']['value']=='Договор перевозки'
    assert result['contract_type']['evidence']=='ДОГОВОР ПЕРЕВОЗКИ'


def test_generic_insurance_heading_does_not_choose_property_over_liability():
    result=postprocess_extraction({'contract_type':{'value':'Договор страхования гражданской ответственности'}},
                                 'PAGE 1\nДоговор страхования\n1. Предмет договора')
    assert result['contract_type']['value']=='Договор страхования гражданской ответственности'
    assert result['contract_type']['status']=='needs_review'


def test_wrapped_explicit_insurance_subtype_is_preserved():
    result=postprocess_extraction({'contract_type':{'value':None}},
                                 'PAGE 1\nДОГОВОР СТРАХОВАНИЯ\nГРАЖДАНСКОЙ ОТВЕТСТВЕННОСТИ № QA-X')
    assert result['contract_type']['value']=='Договор страхования гражданской ответственности'


def test_parenthesized_subtitle_under_agreement_number_is_heading_evidence():
    text='PAGE 1\nДОГОВОР № QA-X\n(займа)\nг. Тверь 08.09.2035\n1. Предмет договора'
    result=postprocess_extraction({'contract_type':{'value':None}},text)['contract_type']
    assert result['value']=='Договор займа'
    assert result['evidence']=='ДОГОВОР № QA-X (займа)'


@pytest.mark.parametrize('labels', [
    'Место подписания: Дата подписания: г. Тверь 08.09.2035',
    'Место подписания: г. Тверь Дата подписания: 08.09.2035',
    'Дата подписания: 08.09.2035 Место подписания: г. Тверь',
])
def test_all_header_values_and_labels_on_one_line(labels):
    result=recover_header_fields({'contract_date':{},'place':{}},'PAGE 1\nДоговор № QA-X '+labels)
    assert result['contract_date']['value']=='2035-09-08'
    assert result['place']['value']=='Тверь'


def test_party_address_between_name_and_inn_does_not_break_identity_record():
    text='Доверитель:\nОрлов Артём Павлович\nПаспорт: серия 4321 номер 654321\nАдрес: г. Тверь, ул. Примерная, д. 3\nИНН: 120000000001'
    proofs=source_links([{'name':'Орлов Артём Павлович','role':'Доверитель'}],text)
    assert len(proofs)==1
    assert next(iter(proofs.values())).keys()=={'120000000001'}


def test_penalty_clause_is_not_classification_evidence():
    quote='За просрочку поставки поставщик платит неустойку.'
    text=f'PAGE 1\nДоговор № QA-X\n1. Предмет договора\nПередача товара.\n2. Ответственность\n{quote}'
    item=postprocess_extraction({'contract_type':{'value':'Договор поставки','evidence':quote}},text)['contract_type']
    assert item['classification_basis']=='unsupported' and item['status']=='needs_review'


def test_header_recovery_runs_after_validation_with_rule_provenance():
    text='PAGE 1\nМесто подписания: Дата подписания:\nг. Тверь 08.09.2035'
    result=merge_extractions([validate_model_result({'contract_date':{'value':None}},text)],text)
    assert result['contract_date']['method']=='rule'
    assert result['contract_date']['value']=='2035-09-08'


def test_type_repair_uses_main_subject_and_retains_review_status():
    quote='Исполнитель обязуется оказать услуги технической поддержки.'
    text=f'PAGE 1\nДоговор № QA-X\n1. Предмет договора\n{quote}\n2. Ответственность\nЗа просрочку поставки уплачивается пеня.'
    first=validate_model_result({'contract_type':{'value':None}},text)
    calls=[]
    def request(prompt):
        calls.append(prompt)
        return json.dumps({'contract_type':{'value':'Договор возмездного оказания услуг','evidence':quote}})
    result,trace=recover_missing(first,text,request,ContractResult.model_json_schema())
    assert len(calls)==1 and trace['accepted']==['contract_type']
    assert result['contract_type']['value']=='Договор возмездного оказания услуг'
    assert result['contract_type']['classification_basis']=='subject'
    assert result['contract_type']['status']=='needs_review'
    bad,_=recover_missing(first,text,lambda _:json.dumps({'contract_type':{
        'value':'Договор поставки','evidence':'За просрочку поставки уплачивается пеня.'}}),ContractResult.model_json_schema())
    assert bad['contract_type']['value'] is None


def test_appendix_subject_is_not_used_for_missing_main_contract_type():
    text='PAGE 1\nДоговор №QA-X\nОбщие условия без указания типа.\nPAGE 2\nПриложение №1\n1. Предмет договора\nПоставщик обязуется передать товар.'
    assert subject_region(text)==''


def test_actual_subject_has_priority_over_earlier_general_provisions():
    quote='Продавец обязуется передать товар, а покупатель обязуется оплатить товар.'
    text=f'PAGE 1\nДоговор №QA-X\n1. Общие положения\nДоговор регулирует отношения сторон.\n2. Предмет договора\n{quote}\n3. Ответственность\nУсловия ответственности.'
    assert quote in subject_region(text)
    assert 'регулирует отношения' not in subject_region(text)
    first=validate_model_result({'contract_type':{'value':None}},text)
    result,trace=recover_missing(first,text,lambda _:json.dumps({'contract_type':{
        'value':'Договор купли-продажи','evidence':quote}}),ContractResult.model_json_schema())
    assert trace['accepted']==['contract_type']
    assert result['contract_type']['classification_basis']=='subject'


def test_legal_form_alias_is_not_a_false_name_grounding_error():
    result=validate_model_result({'parties':[{'name':'ООО «Вектор-Запад»',
        'name_evidence':'Общество с ограниченной ответственностью «Вектор-Запад»'}]},
        'PAGE 1\nОбщество с ограниченной ответственностью «Вектор-Запад»')
    assert 'grounding_reason' not in result['parties'][0]


def test_complete_source_identifier_repairs_a_model_prefix_without_guessing_digits():
    fields={'contract_number':{'value':'AB-5'}}
    result=recover_header_fields(fields,'PAGE 1\nДоговор № AB-5678 г. Тверь 08.09.2035')['contract_number']
    assert result['value']=='AB-5678'
    assert result['source_correction']['previous_value']=='AB-5'
    assert result['status']=='needs_review'


def test_number_quote_preserves_actual_label_spacing_and_date_like_identifier():
    text='PAGE 1\nНомер договора:12.01.2035\nДоговор хранения'
    result=recover_header_fields({'contract_number':{},'contract_date':{}},text)
    assert result['contract_number']['value']=='12.01.2035'
    assert result['contract_number']['evidence']=='Номер договора:12.01.2035'
    assert result['contract_date'].get('value') is None


def test_flattened_number_label_followed_by_date_is_ambiguous():
    text='PAGE 1\nНомер договора:\n08.09.2035\nAB-9\nДоговор хранения'
    assert recover_header_fields({'contract_number':{}},text)['contract_number'].get('value') is None


def test_ocr_source_digits_are_not_changed_to_another_number():
    fields={'contract_number':{'value':'38-91-2035'}}
    assert recover_header_fields(fields,'PAGE 1\nДоговор №38-91-2035')==fields
    conflict=recover_header_fields({'contract_number':{'value':'ZX-99'}},'Договор №AB-5678')['contract_number']
    assert conflict['value']=='ZX-99' and conflict['status']=='needs_review'


def test_monthly_salary_is_qualified_instead_of_claiming_a_contract_total():
    quote='Работнику устанавливается оклад 70000 рублей в месяц.'
    result=validate_model_result({'total_amount':{'value':70000,'evidence':quote}},quote)['total_amount']
    assert result['value']==70000 and result['amount_basis']=='monthly_salary'
    assert result['status']=='needs_review'
    annual='Общая сумма договора 840000 рублей; заработная плата выплачивается ежемесячно.'
    item=validate_model_result({'total_amount':{'value':840000,'evidence':annual}},annual)['total_amount']
    assert 'amount_basis' not in item
