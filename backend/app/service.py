import json
import threading
import uuid
from pathlib import Path
from .rag.core import ContextLimitError,canonical,SAFETY_TOKENS,CONTEXT_LIMIT
from .rag.engine import Generator
from .rag.quality_contract import QualityContract,SourceSelectionContract,compact31
from .rag.data import section_key
from .intent import resolve_task
from .presentation import present_assessed_answer
from .assessment import AssessmentContract

class ExpandedUnavailable(ValueError):pass
class GenerationDisabled(ValueError):pass


def summary_plan(sources,contract,byte_ceiling=18000):
    groups={}
    for source in sources:groups.setdefault(section_key(source),[]).append(source)
    tasks=[]
    for section,items in groups.items():
        batch=[]
        for source in items:
            candidate=batch+[source]
            request=contract.request('Summarize '+section+' of the supplied document.',[getattr(contract,'compact',compact31)(s) for s in candidate],'map',800)
            if len(canonical(request).encode('utf-8'))>byte_ceiling and batch:
                tasks.append({'section':section,'sources':batch});batch=[source]
            else:batch=candidate
        if batch:tasks.append({'section':section,'sources':batch})
    return tasks


def saved_summary_plan(sources,requests_root):
    """Reuse prior partitioning only when the entire current source set matches."""
    from .rag.core import fingerprint
    registry={source['evidence_id']:source for source in sources}
    if not requests_root.exists():return None
    for run in sorted(requests_root.iterdir(),key=lambda path:path.stat().st_mtime,reverse=True):
        summary=run/'summary'
        if not summary.is_dir():continue
        tasks=[];seen=set();valid=True
        for folder in sorted(summary.glob('map-*')):
            try:
                if (folder/'sources.json').exists():
                    prior=json.loads((folder/'sources.json').read_text(encoding='utf8'));ids=list(prior)
                    if fingerprint(prior)!=fingerprint({key:registry[key] for key in ids}):valid=False;break
                else:
                    ids=json.loads((folder/'local-table-ledger.json').read_text(encoding='utf8'))['source_ids']
                    if any(registry[key].get('kind') not in ('table_facts','table_cell') for key in ids):valid=False;break
                if not ids or seen.intersection(ids):valid=False;break
                seen.update(ids);items=[registry[key] for key in ids]
                tasks.append({'section':section_key(items[0]),'sources':items})
            except (OSError,ValueError,KeyError,TypeError):valid=False;break
        if valid and seen==set(registry):return tasks
    return None


def formal_summary_request(contract):
    # Reuse the formal source-selection recovery factory without historical notes/cache.
    def request(question,evidence,mode='qa',max_output_tokens=1800,model=None):
        cleaned=[]
        from .summary_notes import bounded_note
        for item in evidence:
            if mode in ('section_reduce','final_summary') and (item.get('supported_sections') or item.get('original_prose')):
                item=bounded_note(item)
            if item.get('original_prose'):cleaned.extend(item['original_prose'])
            elif 'supported_sections' in item:
                cleaned.append({k:item[k] for k in ('section','supported_sections','numeric_observations') if k in item})
            else:cleaned.append(item)
        output_cap=2400 if mode=='final_summary' else 1500 if mode=='section_reduce' else max_output_tokens
        request=contract.request(question,cleaned,mode,output_cap,model)
        if mode in ('section_reduce','final_summary'):
            # Two section slots previously forced the loss of evaluation/results
            # or conclusions. Keep the existing per-statement and token ceilings.
            request['text']['format']['schema']['properties']['sections']['maxItems']=4
        request['instructions']+='''\nSUMMARY CONTENT PRIORITY (overrides conflicting summary section-count guidance):
Preserve research purpose, method, evaluation setup AND main reported results, and conclusions whenever supplied.
Use up to four nonempty categories: background, method, experiments, conclusion. Do not fill all slots with repeated background/method sections.
During reduction retain each available category, especially experimental findings and conclusions; references/author lists must not displace research findings.
Final summary must use one section per required category; intermediate reductions use one per applicable category and at most four short statements total.
Do not invent missing findings. Cite the actual original source for each retained claim.
Keep Arabic digits out of prose and limitations, INCLUDING section/table labels, model names and implementation settings; omit unnecessary labels or use words. Keep numerical observations in their existing separate field.'''
        if mode=='final_summary':
            from .summary_style import SUMMARY_STYLE
            request['instructions']+=SUMMARY_STYLE
        # Assessment uses the actual wire schema, including this summary-only cap.
        contract.wire_schema=request['text']['format']['schema']
        return request
    return request

class RAGService:
    def __init__(self,store,settings,provider=None,contract_factory=None):
        self.store=store;self.settings=settings;self.provider=provider;self.lock=threading.Lock();self.contract_factory=contract_factory

    def ask(self,document_id,question,context_mode,task='auto'):
        if context_mode=='expanded':
            raise ExpandedUnavailable('expanded context is not supported in this delivery; use baseline.')
        task=resolve_task(question,task)
        corpus=self.store.corpus(document_id)
        if not self.settings.generation_enabled:raise GenerationDisabled('Generation disabled. Set ENABLE_GENERATION=true and OPENAI_API_KEY to use generation; offline tests use a mock provider.')
        with self.lock:
            if self.provider is None:
                from .rag.provider import OpenAIText
                self.provider=OpenAIText(approved=True,budget_usd=self.settings.budget_usd,max_calls=self.settings.max_calls)
            from .manual_review import ManualContract,present_manual,present_partial_manual,compact_source
            contract=self.contract_factory() if self.contract_factory else ManualContract()
            manual=bool(getattr(contract,'manual',False))
            run=self.store.root/document_id/'requests'/uuid.uuid4().hex
            from .summary_evidence import representative_tables
            if manual:contract.summary_user_question=question
            generator=Generator(self.provider,run,self.store.root/document_id/'responses',
                request_factory=formal_summary_request(contract) if task=='summary' and not manual else contract.request,validator=contract.validate,normalizer=contract.normalize,
                compact=compact_source if manual else compact31,validator_version='manual-review-v1' if manual else 'quality-contract-display-v2',retain_fact_ledger=True,local_table_notes=task=='summary',summary_evidence_factory=representative_tables if manual else None,cache_generated_results=False,reuse_saved_responses=False,reuse_compatible_responses=False,failure_handler=contract.recover,saved_request_setup=contract.restore_request,persist_artifacts=False)
            import re
            generator.include_ancillary=bool(re.search(r'appendi|references|bibliograph|附錄|參考文獻',question,re.I))
            pipeline_warnings=[];diagnostics=None;presented=None;is_partial=False
            if task=='summary':
                sources=corpus.summary_sources();tasks=summary_plan(sources,contract)
                summary=generator.summary(sources,tasks)
                from .summary_diagnostics import inspect_summary
                diagnostics=inspect_summary(run,artifacts=generator.artifacts,timestamps=generator.artifact_times)
                registry={s['evidence_id']:s for s in sources}
                is_partial=bool(summary.get('partial_summary'))
                if is_partial:
                    if manual:presented=present_partial_manual(summary['notes'],registry,corpus.document,generator.partial_summary['reason'])
                    else:
                        from .partial_summary import present_partial
                        presented=present_partial(summary['notes'],registry,question,corpus.document,generator.partial_summary['reason'])
                    if not generator.records:raise ContextLimitError('No completed model stage available')
                    record=generator.records[-1]
                else:record=next(r for r in reversed(generator.records) if r['name']==summary['record_name'])
                pipeline_warnings=[{**warning,'stage':item['name']} for item in generator.records if item['name']!=record['name'] for warning in item['validation'].get('warnings',[])]
            else:
                prepared=corpus.qa(question)
                if manual:
                    from .numeric_context import enrich_method_comparison
                    prepared=enrich_method_comparison(question,prepared,corpus.document)
                if not prepared['evidence']:raise ValueError('No matching evidence found; try a question using terms from this document')
                record=generator.qa(question,prepared,'qa')
                registry={k:prepared['registry'][k] for k in record['source_ids']}
            if presented is None:
                presented=present_manual(record['answer'],registry,corpus.document) if manual else present_assessed_answer(record['answer'],registry,question,corpus.document,contract,pipeline_warnings)
            return {**presented,**({'summary_diagnostics':diagnostics} if diagnostics else {}),'context_mode':context_mode,'task':task,
                'input_tokens':record['input_tokens_official'],'cache_hit':record['cache_hit'],
                **({'summary_status':'partial' if is_partial or any(w.get('code')=='summary_coverage' for w in presented.get('validation_warnings',[])) else 'complete'} if task=='summary' else {}),
                'generation':{'status':'stages_completed' if is_partial else 'completed','model':record['model'],'usage':record['usage'],
                    **({'output_reserve':record['max_output_tokens'],'safety_tokens':SAFETY_TOKENS,
                        'budget_total':record['input_tokens_official']+record['max_output_tokens']+SAFETY_TOKENS,'context_limit':CONTEXT_LIMIT} if task=='qa' else {}),
                    'generation_latency_seconds':record['generation_latency_seconds'],
                    'recovered_existing_response':record.get('recovered_existing_response',False),
                    'new_paid_generation':record.get('new_paid_generation',False)}}
