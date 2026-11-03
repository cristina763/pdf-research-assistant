"""Offline summary depth regression; synthetic evidence, no saved answers."""
import copy
import re
import pytest
from app.manual_review import ManualContract, present_manual, compact_source
from app.table_results import NumericPresentationError, render_tables
from app.summary_style import detailed_summary


def evidence():
    registry={}
    for index,section in enumerate(('Purpose','Method','Results','Conclusion'),1):
        registry[f'C{index}']={'text':('Synthetic source evidence describes research purpose, retrieval, evaluation, '
            'dataset-dependent exceptions and limited generalization. ')*6,
            'page_numbers':[index],'section_path':[section],'source_refs':[]}
    facts=[]
    for dataset in ('Alpha','Beta','Gamma'):
        for metric in ('Overall','Diversity'):
            for method,value in (('System','60%'),('Reference','40%')):
                facts.append({'fact_id':f'{dataset}-{metric}-{method}','table_id':'t1','table_number':1,
                    'dataset':dataset,'metric':metric,'method':method,
                    'comparison_methods':['System','Reference'],'value':value})
    registry['C5']={'text':'Original parsed table data','page_numbers':[5], 'facts':facts,'table_id':'t1'}
    for key,source in registry.items():source['evidence_id']=key
    return registry


def payload(mode='summary',question='summary this document.'):
    # These are fixture statements, not an archived or generated answer.
    texts=(
        'The study investigates how to retrieve connected evidence for document questions while preserving the context needed to explain an answer. Its purpose is to improve the usefulness of retrieval when relevant information is spread across passages rather than concentrated in a single extract.',
        'The proposed method builds an index of passages and their relationships, then combines focused retrieval with broader contextual search. It integrates the selected evidence before generating a response and supports updates to the indexed material. This combines local detail with context for questions requiring several related pieces of evidence.',
        'Evaluation compares the proposed system with reference approaches across several datasets and response criteria. The authors report stronger responses in the main comparison, but the evidence also includes dataset-dependent exceptions. These exceptions limit any claim that the complete system is always superior. The experimental conditions and paired reference must be considered when interpreting the reported results.',
        'The findings support combining connected evidence with passage retrieval for the evaluated tasks. Generalization remains limited by the evaluation setting, and the reported relationships do not establish universal superiority or statistical significance. The conclusion is that the approach is useful under the tested conditions, while the original evidence should guide judgments about applicability to a different document collection.')
    return {'sections':[{'category':cat,'title':cat,'statements':[{'text':text,'support':[{'source_id':f'C{i}'}]}]}
        for i,(cat,text) in enumerate(zip(('background','method','experiments','conclusion'),texts),1)],
        'table_views':[],'numeric_observations':[],'limitations':[],'evidence_status':'partial',
        'source_quotes':[{'source_id':'C3'},{'source_id':'C4'}],
        'numeric_presentation':{'mode':mode,'question':question}}


def test_a1_concise_complete_and_full_evidence(capsys):
    registry=evidence();raw=payload();contract=ManualContract()
    answer,_=contract.normalize(raw,registry)
    text=answer['answer_markdown']
    assert 200<=len(re.findall(r'\b[\w-]+\b',text))<=350
    assert all(section['category'] in text for section in raw['sections'])
    assert 'dataset-dependent exceptions' in text and 'Generalization remains limited' in text
    assert '> ' not in text and '| Dataset' not in text and 'computed ordering' not in text
    assert contract.validate(answer,registry)['status']=='mapped'
    assert len(answer['numeric_claims'])==len(render_tables(registry,'',True)[2])
    assert 'C3' in answer['covered_source_ids'] and 'C5' in answer['covered_source_ids']
    result=present_manual(answer,registry,{'tables':[{'table_id':'t1','table_number':1,'grid':[['Original','cells']]}]})
    assert len(result['sources'])==5 and result['supporting_tables'][0]['native_grid']
    # Measure the former append-only overhead against the SAME prose, rather
    # than claiming a real-model before/after comparison.
    old=text+'\n\n'+'\n\n'.join(registry[k]['text'] for k in ('C3','C4'))+'\n\n'+render_tables(registry,'',True)[0]
    print(f'CONTROLLED_RENDER_LENGTH before={len(old)} after={len(text)} words={len(text.split())}')


@pytest.mark.parametrize('question',[
    'Compare System versus Reference with detailed values.',
    'Explain every ablation variant and show Table 1 with numerical values.'])
def test_a2_a3_keep_full_numeric_output(question):
    registry=evidence();raw=payload('qa',question)
    answer,_=ManualContract().normalize(raw,registry)
    table,ids,claims=render_tables(registry,question,False)
    assert table not in answer['answer_markdown']
    assert 'Source explanations (verbatim' not in answer['answer_markdown']
    assert answer['supporting_evidence']['numeric_markdown']==table
    assert answer['supporting_evidence']['numeric_claims']==claims
    assert set(ids)<={item['evidence_id'] for item in answer['supporting_evidence']['citations']}
    assert 'dataset-dependent exceptions' in answer['answer_markdown']


def test_conflicting_cells_still_rejected_for_a1():
    registry=evidence();fact=copy.deepcopy(registry['C5']['facts'][0]);fact['value']='99%'
    registry['C5']['facts'].append(fact)
    with pytest.raises(NumericPresentationError):ManualContract().normalize(payload(),registry)


def test_original_prose_fallback_is_preserved():
    raw=payload();raw['sections']=[]
    answer,_=ManualContract().normalize(raw,evidence())
    assert 'Original evidence fallback' in answer['answer_markdown']
    assert '> Synthetic source evidence' in answer['answer_markdown']


def test_generated_numbers_do_not_escape_numeric_guard():
    raw=payload();raw['sections'][2]['statements'][0]['text']='The system achieves 99% everywhere.'
    answer,_=ManualContract().normalize(raw,evidence())
    assert '99%' not in answer['answer_markdown']
    assert 'C3' in answer['covered_source_ids']


def test_summary_prompt_and_explicit_depth():
    contract=ManualContract();contract.summary_user_question='summary this document.'
    request=contract.request('Integrate notes',list(map(compact_source,evidence().values())),'final_summary')
    assert '200-350' in request['instructions'] and '300-500' in request['instructions']
    support=request['text']['format']['schema']['properties']['sections']['items']['properties']['statements']['items']['properties']['support']
    assert 'C3' in support['items']['properties']['source_id']['enum']
    assert not detailed_summary('summary this document.')
    for question in ('Summarize with detailed tables','請提供詳細摘要及數值排序'):
        assert detailed_summary(question)
    answer,_=contract.normalize(payload(question='Summarize with detailed tables'),evidence())
    assert 'computed ordering' in answer['answer_markdown']
