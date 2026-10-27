from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile
import pytest

from src.evaluation import score_gold, score_pages, vat_components
from src.evaluation_labels import load_labels
from scripts import benchmark_dataset as benchmark
from tools.make_dataset import install_archive


def gold():
    field = lambda v, page=1: {'normalized_value': v, 'status': 'present', 'evidence': [{'text': 'Контрольный фрагмент', 'page': page}]}
    return {'document_id': 'contract_001', 'document_tags': {}, 'files': {'pdf': 'Договор_001.pdf'}, 'gold': {
        'contract_number': field('42'), 'contract_date': field('2026-09-15'), 'contract_type': field('Договор поставки'),
        'place': field('г. Москва'), 'term': field('2026-12-31'), 'total_amount': field(1000) | {'currency': 'RUB'},
        'vat': field(20) | {'mode': 'included'},
        'parties': [{'order': i, 'name': field(name), 'inn': field(inn)} for i, name, inn in [(1, 'ООО Альфа', '111'), (2, 'ООО Бета', '222')]],
    }}


def prediction():
    return {key: {'value': val, 'page_number': 1} for key, val in [('contract_number','42'),('contract_date','2026-09-15'),('contract_type','Договор поставки'),('place','Москва'),('term','2026-12-31'),('total_amount',1000)]} | {
        'vat': {'rate': 20, 'mode': 'included', 'page_number': 1},
        'parties': [{'name': name, 'inn': inn, 'name_page_number': 1, 'inn_page_number': 1} for name, inn in [('ООО Альфа','111'),('ООО Бета','222')]],
    }


def test_structured_gold_all_eleven_values_and_party_order():
    result = prediction();result['parties'].reverse()
    assert len(score_gold(gold(),result)) == 11
    assert all(score_gold(gold(),result).values())
    result['parties'][0]['inn'], result['parties'][1]['inn'] = result['parties'][1]['inn'], result['parties'][0]['inn']
    assert not score_gold(gold(),result)['party1_inn']
    assert not score_gold(gold(),result)['party2_inn']


def test_zero_rate_and_exemption_are_not_equivalent():
    document = gold();document['gold']['vat']['normalized_value'] = 0
    result = prediction();result['vat'] = {'rate': 0, 'mode': 'not_subject'}
    assert score_gold(document,result)['vat'] is False
    document['gold']['vat']['mode'] = 'not_applicable'
    result['vat']['rate'] = None
    assert score_gold(document,result)['vat'] is True
    result['vat']['mode'] = 'not_stated'
    assert score_gold(document,result)['vat'] is False


def test_not_found_vat_is_not_a_zero_rate_even_with_upstream_default_zero():
    document = gold();document['gold']['vat'].update(status='not_found', normalized_value=0, mode=None, evidence=[])
    result = prediction();result['vat'] = {'rate': None,'mode': 'not_stated'}
    assert all(vat_components(document,result).values())
    result['vat'] = {'rate': 0,'mode': 'included'}
    assert score_gold(document,result)['vat'] is False


def test_pdf_page_matching_preserves_party_identity():
    document = gold();document['gold']['parties'][0]['name']['evidence'][0]['page'] = 3
    result = prediction();result['parties'][0]['name_page_number'] = 3;result['parties'].reverse()
    assert all(score_pages(document,result).values())


def test_numbered_labels_take_precedence_only_when_explicitly_selected(tmp_path):
    path = tmp_path/'meta';path.mkdir();(path/'schema.json').write_text('{}')
    (path/'1.json').write_text(json.dumps(gold()))
    labels, provenance = load_labels(path)
    assert set(labels) == {1} and provenance['format'] == 'structured'
    (path/'1.json').write_text(json.dumps(gold() | {'document_id':'contract_002'}))
    with pytest.raises(ValueError,match='ID mismatch'):load_labels(path)


def test_missing_full_metadata_does_not_silently_use_legacy(tmp_path):
    with pytest.raises(FileNotFoundError,match='separate meta.zip'):
        load_labels(tmp_path/'meta')


def test_invalid_gold_date_is_rejected_instead_of_passing_none_equals_none(tmp_path):
    document=gold();document['gold']['term']['normalized_value']='invalid'
    (tmp_path/'1.json').write_text(json.dumps(document))
    with pytest.raises(ValueError,match='Unparseable'):load_labels(tmp_path)


def test_archive_restore_flattens_nested_meta_without_overwriting_edits(tmp_path):
    archive=tmp_path/'meta.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('meta/1.json',json.dumps(gold()))
        z.writestr('__MACOSX/meta/._1.json','ignored')
    destination=tmp_path/'meta'
    assert install_archive(archive,destination,labels=True)['files'] == 1
    assert (destination/'1.json').exists()
    (destination/'1.json').write_text('operator edits')
    with pytest.raises(FileExistsError):install_archive(archive,destination,labels=True)
    assert (destination/'1.json').read_text()=='operator edits'


def test_rescore_uses_saved_fields_without_modifying_originals(tmp_path,monkeypatch):
    labels=tmp_path/'labels';labels.mkdir();(labels/'1.json').write_text(json.dumps(gold()))
    source=tmp_path/'original';source.mkdir()
    manifest={'completed':True,'files':[{'document_id':1,'format':'pdf','input_hash':'input','labeled':False}], 'inventory':{'files':1}}
    (source/'manifest.json').write_text(json.dumps(manifest))
    for backend in ('local','api'):
        report={'completed':True,'config':{'code_hash':'frozen','label_hash':'old'},'records':[{'document_id':1,'format':'pdf','input_hash':'input','status':'ok','fields':prediction(),'extraction_sec':1}]}
        (source/f'{backend}.json').write_text(json.dumps(report))
    previous={p.name:p.read_bytes() for p in source.iterdir()}
    monkeypatch.setattr(benchmark,'code_hash',lambda:'scoring-version')
    output=tmp_path/'rescored'
    benchmark.rescore(SimpleNamespace(source_results=source,output=output,labels=labels))
    result=json.loads((output/'comparison.json').read_text())
    assert result['paired_files']==1
    assert result['summary']['local']['correct_fields']==11
    assert '1 contract IDs' in result['limitations'][0]
    assert result['vat_components']['local']['mode']=={'correct':1,'total':1}
    assert {p.name:p.read_bytes() for p in source.iterdir()}==previous
    with pytest.raises(ValueError):benchmark.rescore(SimpleNamespace(source_results=source,output=source,labels=labels))


def test_failed_extraction_cannot_pass_missing_vat_component():
    document=gold();document['gold']['vat'].update(status='not_found',normalized_value=None,mode=None)
    record={'status':'error','format':'pdf'}
    benchmark.apply_scores(record,document)
    assert not any(record['field_scores'].values())
    assert not any(record['vat_components'].values())


def test_partial_labels_require_explicit_opt_in():
    with pytest.raises(ValueError, match='Missing labels'):
        benchmark.require_label_coverage({1: gold()}, [1, 2])
    benchmark.require_label_coverage({1: gold()}, [1, 2], allow_unlabeled=True)


def test_reviewed_labels_are_a_separate_version_bound_copy(tmp_path,monkeypatch):
    from scripts import review_dataset_labels as reviewer
    source=tmp_path/'source';source.mkdir();path=source/'1.json';path.write_text(json.dumps(gold()))
    original=path.read_bytes();_,provenance=load_labels(source)
    monkeypatch.setattr(reviewer,'UPSTREAM_HASH',provenance['sha256'])
    monkeypatch.setattr(reviewer,'FIXES',[(1,('gold','contract_number','normalized_value'),'42','43','Synthetic correction test')])
    output=tmp_path/'reviewed'
    manifest=reviewer.reviewed_copy(source,output)
    assert path.read_bytes()==original
    assert json.loads((output/'1.json').read_text())['gold']['contract_number']['normalized_value']=='43'
    assert len(manifest['changes'])==1
    monkeypatch.setattr(reviewer,'UPSTREAM_HASH','different-source')
    with pytest.raises(ValueError,match='verified upstream snapshot'):
        reviewer.reviewed_copy(source,tmp_path/'must-not-exist')
    assert not (tmp_path/'must-not-exist').exists()
