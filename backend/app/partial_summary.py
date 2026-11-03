"""Readable, explicitly partial output from strictly validated stage findings."""
from .summary_notes import bounded_children,CATEGORIES
from .rag.quality_contract import QualityContract
from .rag.core import ContextLimitError
from .presentation import present_answer


def present_partial(notes,registry,question,document,reason):
    note=bounded_children({'section':'Partial summary'},notes)
    sections=note.get('supported_sections',[])
    if not any(s['statements'] for s in sections):
        raise ContextLimitError('No trustworthy readable stage findings available for a partial summary')
    payload={'sections':sections,'table_views':[],'numeric_observations':[],
        'limitations':[],'evidence_status':'partial'}
    contract=QualityContract()
    answer,_=contract.normalize(payload,registry)
    contract.validate(answer,registry)
    result=present_answer(answer,registry,question,document)
    actual={s['category'] for s in sections}
    missing=[category for category in CATEGORIES if category not in actual]
    warning={'code':'partial_summary','message':reason,'severity':'review','source_ids':[],
        'stage':'summary/reduction'}
    result.update(summary_status='partial',validation_status='review_required',validation_warnings=[warning],
        unverified_sources=[],validation={**result['validation'],'status':'review_required','warnings':[warning],
            'summary_completeness':'not_certified','missing_categories':missing,'origin':'validated_stage_findings_not_final_generation'})
    return result
