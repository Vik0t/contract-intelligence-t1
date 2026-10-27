from copy import deepcopy

from src.extraction.summary import _format_fields_block, summarize_document


def test_model_context_excludes_trace_prompts_and_coordinates_without_mutating_results():
    fields={'total_amount':{'value':700,'currency':'RUB','status':'found','evidence':'SOURCE_ONLY'},
            'parties':[{'name':'Alpha LLC','role':'Поставщик','inn':'1234567890',
                        'inn_link':{'source_sha256':'TRACE_ONLY'},'name_evidence':'SOURCE_ONLY'}],
            '_provenance':{'prompts':['TRACE_ONLY'*10000]},'_quality':{'technical':'TRACE_ONLY'},
            '_repair':{'requested':['TRACE_ONLY']}}
    original=deepcopy(fields)
    rendered=_format_fields_block(fields)
    assert len(rendered)<500 and 'Alpha LLC' in rendered and '700' in rendered
    assert 'TRACE_ONLY' not in rendered and 'SOURCE_ONLY' not in rendered
    assert fields==original


def test_summary_receives_document_and_semantic_fields_without_extraction_metadata(monkeypatch):
    from src.extraction import summary
    monkeypatch.setenv('SUMMARY_BACKEND','local')
    prompts=[]
    def generate(prompt,*args):
        prompts.append(prompt)
        return 'Краткое содержание.'
    monkeypatch.setattr(summary,'_summarize_local',generate)
    assert summarize_document('ДОГОВОР ПОСТАВКИ',{'contract_number':{'value':'TEST-1'},
        '_provenance':{'prompts':['TRACE_ONLY']}})=='Краткое содержание.'
    assert 'ДОГОВОР ПОСТАВКИ' in prompts[0] and 'TEST-1' in prompts[0]
    assert 'TRACE_ONLY' not in prompts[0]
