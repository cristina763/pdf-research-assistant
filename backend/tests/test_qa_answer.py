"""Answer and evidence are independent: citations/tables cannot repair prose."""
import copy
import json
import pytest
from app.manual_review import ManualContract,compact_source,present_manual
from app.table_results import NumericPresentationError
from test_summary_presentation import evidence,payload
from test_basic import setup,upload,state
from helpers import MockText


def test_experimental_sources_can_generate_answer_without_method_source():
    registry=evidence()
    for source in registry.values():source['section_path']=['Results and ablations']
    request=ManualContract().request('Explain the experimental findings',[compact_source(s) for s in registry.values()])
    assert request['text']['format']['schema']['properties']['sections'].get('maxItems')!=0
    assert request['text']['format']['schema']['properties']['sections']['minItems']==1
    assert 'source selection alone is not an answer' in request['instructions']
    quote_ids=request['text']['format']['schema']['properties']['source_quotes']['items']['properties']['source_id']['enum']
    assert 'C3' in quote_ids and 'C5' not in quote_ids


def test_empirical_analysis_survives_backend_and_api_separates_evidence():
    registry=evidence();raw=payload('qa','Compare the systems')
    answer,_=ManualContract().normalize(raw,registry)
    assert all(s['statements'][0]['text'] in answer['answer_markdown'] for s in raw['sections'])
    assert '> ' not in answer['answer_markdown'] and '| Dataset' not in answer['answer_markdown']
    result=present_manual(answer,registry,{'tables':[]})
    assert result['answer_status']=='answered'
    assert result['supporting_evidence']['numeric_claims']
    assert 'C5' not in {c['evidence_id'] for c in result['answer']['citations']}
    assert 'C5' in {s['evidence_id'] for s in result['sources']}


@pytest.mark.parametrize('text',['','[C3]','[C1, C2]','> Original quoted evidence.','| Method | Rate |\n| --- | --- |\n| System | high |','System > Reference'])
def test_evidence_only_cannot_be_successful_answer(text):
    raw=payload('qa','Explain findings')
    raw['sections']=[{'category':'experiments','title':'Evidence','statements':[{'text':text,'support':[{'source_id':'C3'}]}]}]
    with pytest.raises(NumericPresentationError):ManualContract().normalize(raw,evidence())


def test_empty_sections_with_complete_tables_are_rejected():
    raw=payload('qa','Explain findings');raw['sections']=[]
    with pytest.raises(NumericPresentationError):ManualContract().normalize(raw,evidence())


def test_valid_mixed_answer_keeps_all_generated_parts():
    raw=payload('qa','Explain findings')
    raw['sections'][0]['statements'].extend([
        {'text':'> Short source quotation.','support':[{'source_id':'C1'}]},
        {'text':'[C1]','support':[{'source_id':'C1'}]},
        {'text':'| Method | Outcome |\n| --- | --- |\n| System | mixed |','support':[{'source_id':'C1'}]},
    ])
    answer,_=ManualContract().normalize(raw,evidence())
    assert all(statement['text'] in answer['answer_markdown'] for section in raw['sections'] for statement in section['statements'])
    assert answer['answer_integrity']=={'model_statement_count':7,'preserved_statement_count':7}


def test_citation_digits_are_not_numbers_and_unknown_markers_do_not_delete_answer():
    raw=payload('qa','Explain findings')
    raw['sections'][0]['statements'][0]['text']='The study investigates retrieval. [C1]'
    answer,_=ManualContract().normalize(raw,evidence())
    assert answer['answer_markdown'].count('The study investigates retrieval. [C1]')==1
    for marker in ('C 1','C1, C2'):
        raw['sections'][0]['statements'][0]['text']=f'The study investigates retrieval. [{marker}]'
        answer,_=ManualContract().normalize(raw,evidence())
        assert raw['sections'][0]['statements'][0]['text'] in answer['answer_markdown']
    for marker in ('C99','Csix','Critic support: CA?'):
        raw['sections'][0]['statements'][0]['text']=f'The study investigates retrieval. [{marker}]'
        answer,_=ManualContract().normalize(raw,evidence())
        assert raw['sections'][0]['statements'][0]['text'] in answer['answer_markdown']
        assert any(w['code']=='unmapped_citation' for w in answer['citation_warnings'])
        assert marker not in {c['evidence_id'] for c in answer['citations']}


def test_insufficient_evidence_is_explained_in_answer():
    raw=payload('qa','Explain missing evidence');raw['evidence_status']='insufficient'
    raw['sections']=[{'category':'answer','title':'','statements':[
        {'text':'The supplied material does not describe the requested comparison, so its relative performance cannot be determined.','support':[]}]}]
    raw['source_quotes']=[]
    answer,_=ManualContract().normalize(raw,{})
    assert answer['answer_status']=='insufficient_evidence' and not answer['citations']
    assert answer['answer_markdown'] and not answer['supporting_evidence']['numeric_markdown']


def test_generated_numbers_are_rejected_and_conflicting_evidence_is_withheld():
    raw=payload('qa','Explain findings');raw['sections'][2]['statements'][0]['text']='System scores 99%.'
    with pytest.raises(NumericPresentationError):ManualContract().normalize(raw,evidence())
    registry=evidence();bad=copy.deepcopy(registry['C5']['facts'][0]);bad['value']='99%'
    registry['C5']['facts'].append(bad)
    from app.table_results import render_tables
    with pytest.raises(NumericPresentationError):render_tables(registry,'Explain findings')
    raw=payload('qa','Explain findings')
    answer,_=ManualContract().normalize(raw,registry)
    assert all(s['statements'][0]['text'] in answer['answer_markdown'] for s in raw['sections'])
    assert answer['supporting_evidence']['numeric_claims']==[]
    assert answer['supporting_evidence']['numeric_markdown']==''
    assert answer['citation_warnings'][0]['code']=='supporting_numeric_unavailable'


def test_auxiliary_failures_cannot_delete_or_replace_answer(monkeypatch):
    import app.table_results as tables
    raw=payload('qa','Explain findings')
    raw['source_quotes'].append({'source_id':'C99'})
    def broken(*args,**kwargs):raise RuntimeError('Synthetic auxiliary renderer failure')
    monkeypatch.setattr(tables,'render_tables',broken)
    answer,_=ManualContract().normalize(raw,evidence())
    assert all(s['statements'][0]['text'] in answer['answer_markdown'] for s in raw['sections'])
    assert answer['answer_integrity']=={'model_statement_count':4,'preserved_statement_count':4}
    assert len(answer['citation_warnings'])==2
    assert ManualContract().validate(answer,evidence())['status']=='unmapped'


def test_native_source_presentation_failure_cannot_erase_valid_answer():
    raw=payload('qa','Explain findings')
    answer,_=ManualContract().normalize(raw,evidence())
    result=present_manual(answer,evidence(),{'tables':[{}]})
    assert result['answer']['answer_markdown']==answer['answer_markdown']
    assert result['answer_integrity']['model_statement_count']==4
    assert result['citation_warnings'][-1]['code']=='source_presentation_unavailable'


def test_api_returns_complete_generated_answer_despite_auxiliary_reference_error(tmp_path):
    class AnswerWithBadSidecar(MockText):
        def generate(self,request):
            result=super().generate(request)
            raw=json.loads(result['output'][0]['content'][0]['text'])
            raw['source_quotes']=[{'source_id':'C99'}]
            self.generated_texts=[s['text'] for section in raw['sections'] for s in section['statements']]
            result['output'][0]['content'][0]['text']=json.dumps(raw)
            return result
    provider=AnswerWithBadSidecar();client,_,_,_=setup(tmp_path,provider)
    document=upload(client).json()['document_id'];before=state(tmp_path)
    response=client.post('/ask',json={'document_id':document,'question':'Explain retrieval evidence'})
    assert response.status_code==200,response.text
    body=response.json()
    assert all(text in body['answer']['answer_markdown'] for text in provider.generated_texts)
    assert body['answer_integrity']['model_statement_count']==body['answer_integrity']['preserved_statement_count']
    assert body['citation_warnings'][0]['code']=='invalid_supporting_reference'
    assert state(tmp_path)==before


def test_numeric_safety_is_in_wire_schema_not_destructive_rewriting():
    request=ManualContract().request('Compare systems',[compact_source(s) for s in evidence().values()])
    text_schema=request['text']['format']['schema']['properties']['sections']['items']['properties']['statements']['items']['properties']['text']
    from jsonschema import validate,ValidationError
    validate('Source-backed qualitative analysis.',text_schema)
    with pytest.raises(ValidationError):validate('System scores 99%.',text_schema)


def test_context_keeps_exact_pairwise_scope_and_original_rows():
    from app.numeric_context import pack_large_tables
    source=copy.deepcopy(evidence()['C5'])
    originals=copy.deepcopy(source['facts'])
    for fact in originals:
        extra=copy.deepcopy(fact)
        extra['comparison_methods']=['Variant','Reference']
        if extra['method']=='System':
            extra['method']='Variant'
            extra['value']={'Alpha':'70%','Beta':'50%','Gamma':'60%'}[extra['dataset']]
        source['facts'].append(extra)
    wire=pack_large_tables([compact_source(source)],threshold=0,question='Compare Variant with System')[0]
    report=next(r for r in wire['computed_comparisons']['reports'] if r['metric']=='Overall')
    pair=next(p for p in report['pairwise_rate_patterns'] if {p['left'],p['right']}=={'System','Variant'})
    assert pair['lower']==['Alpha'] and pair['higher']==['Beta'] and pair['equal']==['Gamma']
    assert sum(len(group['rows'])*(len(group['columns'])-1) for group in wire['table_fact_groups'])==len(source['facts'])


def test_api_rejects_evidence_only_generation_without_persistence(tmp_path):
    class EvidenceOnly(MockText):
        def generate(self,request):
            result=super().generate(request)
            raw=json.loads(result['output'][0]['content'][0]['text'])
            raw['sections']=[]
            result['output'][0]['content'][0]['text']=json.dumps(raw)
            return result
    client,_,_,provider=setup(tmp_path,EvidenceOnly())
    document=upload(client).json()['document_id'];before=state(tmp_path)
    response=client.post('/ask',json={'document_id':document,'question':'Explain retrieval evidence'})
    assert response.status_code==422 and response.json()['validation_status']=='rejected'
    assert state(tmp_path)==before and provider.calls==1


def test_broken_json_is_not_recovered_as_a_successful_qa_answer(tmp_path):
    class Broken(MockText):
        def generate(self,request):
            result=super().generate(request)
            result['output'][0]['content'][0]['text']='{"sections":'
            return result
    client,_,_,provider=setup(tmp_path,Broken())
    document=upload(client).json()['document_id'];before=state(tmp_path)
    response=client.post('/ask',json={'document_id':document,'question':'Explain retrieval evidence'})
    assert response.status_code==422 and state(tmp_path)==before and provider.calls==1
