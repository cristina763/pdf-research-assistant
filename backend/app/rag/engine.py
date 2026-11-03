"""Grounded generation; website diagnostics stay in request-local memory."""
import json
import time
import traceback
from collections import OrderedDict
from pathlib import Path

from .core import (make_request,count_payload,enforce_budget,worst_cost,response_text,validate_answer,
                  fingerprint,ContextLimitError,CONTEXT_LIMIT,SAFETY_TOKENS)
from .core import complete_unique_table_claims,GroundingError,canonical,IncompleteResponse
from .data import Corpus
from copy import deepcopy as copy_sections


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


class Generator:
    def __init__(self,provider,output,cache,request_factory=None,validator=None,normalizer=None,compact=None,validator_version='v1',retain_fact_ledger=False,local_table_notes=False,reuse_saved_responses=False,failure_handler=None,saved_request_setup=None,reuse_compatible_responses=False,cache_generated_results=True,summary_evidence_factory=None,persist_artifacts=True):
        self.provider=provider;self.output=Path(output);self.cache=Path(cache);self.records=[]
        self.request=request_factory or make_request;self.validate=validator or validate_answer
        self.normalize=normalizer or complete_unique_table_claims;self.compact=compact or Corpus.compact
        self.validator_version=validator_version;self.retain_fact_ledger=retain_fact_ledger;self.full_registry={}
        self.persist_artifacts=persist_artifacts;self.artifacts={};self.artifact_times={}
        self.local_table_notes=local_table_notes
        self.reuse_saved_responses=reuse_saved_responses and persist_artifacts
        self.failure_handler=failure_handler
        self.saved_request_setup=saved_request_setup
        self.reuse_compatible_responses=reuse_compatible_responses and persist_artifacts
        self.cache_generated_results=cache_generated_results and persist_artifacts
        self.summary_evidence_factory=summary_evidence_factory;self.summary_numeric_evidence=[]
        self.include_ancillary=False

    def _save(self,path,value):
        # Disk recording is retained for explicit offline/development callers.
        # RAGService always disables it; no request directory is created there.
        if self.persist_artifacts:
            save(path,value)
        else:
            key=Path(path).relative_to(self.output).as_posix()
            self.artifacts[key]=copy_sections(value)
            self.artifact_times[key]=time.time()

    def _saved_artifacts(self,request,registry=None):
        if not self.cache_generated_results or not self.reuse_saved_responses:return None
        root=self.cache.parent/'requests'
        if not root.is_dir():return None
        for path in sorted(root.rglob('request.json'),key=lambda p:((p.parent/'transport-metrics.json').exists(),p.stat().st_mtime),reverse=True):
            folder=path.parent
            try:
                stored=json.loads(path.read_text(encoding='utf-8'))
                if fingerprint(stored)!=fingerprint(request):
                    if not (self.reuse_compatible_responses and registry is not None and stored['model']==request['model']):continue
                    old_data=json.loads(stored['input'][0]['content'][0]['text'])
                    new_data=json.loads(request['input'][0]['content'][0]['text'])
                    if old_data['task']!=new_data['task'] or old_data['question']!=new_data['question']:continue
                    # A numerical QA evidence revision must not replay an answer
                    # generated from the previous, broader numerical context.
                    if old_data.get('numeric_evidence_revision')!=new_data.get('numeric_evidence_revision'):continue
                count=json.loads((folder/'input-count.json').read_text(encoding='utf-8'))
                if count['request_sha256']!=fingerprint(count_payload(stored)):continue
                enforce_budget(count['official_input_tokens'],stored['max_output_tokens'])
                if registry is not None and fingerprint(json.loads((folder/'sources.json').read_text(encoding='utf-8')))!=fingerprint(registry):continue
                raw=json.loads((folder/'raw-response.json').read_text(encoding='utf-8'))
                if raw.get('status')!='completed':continue
                metrics=json.loads((folder/'transport-metrics.json').read_text(encoding='utf-8')) if (folder/'transport-metrics.json').exists() else {}
                return {'raw':raw,'count':count['official_input_tokens'],'folder':str(folder),'latency':metrics.get('generation_latency_seconds'),'request':stored}
            except (OSError,ValueError,KeyError,TypeError):continue
        return None

    def fits(self,request,registry=None):
        saved=self._saved_artifacts(request,registry)
        count=saved['count'] if saved else self.provider.count_input(request)
        try:enforce_budget(count,request['max_output_tokens']);return True
        except ContextLimitError:return False

    def call(self,name,request,registry):
        prior=self._saved_artifacts(request,registry)
        if prior and self.reuse_compatible_responses:request=prior['request']
        key=fingerprint({'request':request,'registry':registry,'validator':self.validator_version})
        cached=self.cache/key/'result.json';folder=self.output/name
        if self.persist_artifacts:folder.mkdir(parents=True,exist_ok=True)
        reusable_raw=self.cache_generated_results and (folder/'raw-response.json').exists() and (folder/'request.json').exists() and fingerprint(json.loads((folder/'request.json').read_text(encoding='utf-8')))==fingerprint(request)
        if self.cache_generated_results:self._save(folder/'request.json',request)
        else:
            data=json.loads(request['input'][0]['content'][0]['text'])
            self._save(folder/'request.json',{'model':request['model'],'max_output_tokens':request['max_output_tokens'],
                'request_sha256':fingerprint(request),'input_count_payload_sha256':fingerprint(count_payload(request)),
                'task':data['task'],'question':data['question'],'source_ids':list(registry),
                'request_evidence_bytes':len(canonical(data['evidence']).encode('utf8')),
                'generated_text_retained':False})
        self._save(folder/'sources.json',registry)
        try:
            if self.cache_generated_results and cached.exists():
                record=json.loads(cached.read_text(encoding='utf-8'))
                self.validate(record['answer'],registry)
                enforce_budget(record['input_tokens_official'],request['max_output_tokens'])
                record={**record,'cache_hit':True,'new_paid_generation':False}
                if record.get('generation_latency_seconds') is None and prior:
                    record['generation_latency_seconds']=prior['latency']
            else:
                tick=time.perf_counter()
                count=(json.loads((folder/'input-count.json').read_text(encoding='utf-8'))['official_input_tokens']
                       if reusable_raw else prior['count'] if prior else self.provider.count_input(request))
                count_latency=time.perf_counter()-tick
                self._save(folder/'input-count.json',{'model':request['model'],'request_sha256':fingerprint(count_payload(request)),
                    'official_input_tokens':count,'output_reserve':request['max_output_tokens'],'safety':SAFETY_TOKENS,'limit':CONTEXT_LIMIT})
                enforce_budget(count,request['max_output_tokens'])
                if not reusable_raw and not prior and hasattr(self.provider,'budget_usd'):
                    reservation=worst_cost(count,request['max_output_tokens'])
                    self._save(folder/'budget-before-call.json',{'approved_cap_usd':self.provider.budget_usd,
                        'previous_reserved_usd':self.provider.spent_ceiling,'this_call_max_usd':reservation,
                        'remaining_after_reservation_usd':self.provider.budget_usd-self.provider.spent_ceiling-reservation})
                tick=time.perf_counter()
                raw=(json.loads((folder/'raw-response.json').read_text(encoding='utf-8'))
                     if reusable_raw else prior['raw'] if prior else self.provider.generate(request))
                latency=(prior['latency'] if prior else None) if reusable_raw or prior else time.perf_counter()-tick
                if self.cache_generated_results:self._save(folder/'raw-response.json',raw)
                if not reusable_raw and not prior:
                    self._save(folder/'transport-metrics.json',{'generation_latency_seconds':latency,
                         'count_latency_seconds':count_latency})
                if raw.get('status')!='completed':raise IncompleteResponse('Incomplete/failed response; diagnostics retained without automatic paid retry')
                usage=raw.get('usage',{})
                if not all(isinstance(usage.get(k),int) and not isinstance(usage.get(k),bool) and usage[k]>=0
                           for k in ('input_tokens','output_tokens','total_tokens')):
                    raise RuntimeError('Actual API token usage missing or invalid; request diagnostics retained')
                if usage['total_tokens']!=usage['input_tokens']+usage['output_tokens']:
                    raise RuntimeError('Inconsistent actual API token usage')
                if usage.get('input_tokens',count)+usage.get('output_tokens',0)>CONTEXT_LIMIT:
                    raise ContextLimitError('Actual usage exceeds application context policy')
                self._save(folder/'generation.json',{'status':'completed','model':raw.get('model',request['model']),
                    'response_id':raw.get('id'),'usage':usage,'generation_latency_seconds':latency,
                    'recovered_from':prior['folder'] if prior else None})
                text=response_text(raw)
                try:
                    answer,repairs=self.normalize(json.loads(text),registry)
                    validation=self.validate(answer,registry)
                except (GroundingError,json.JSONDecodeError) as error:
                    if self.failure_handler is None:raise
                    answer,validation=self.failure_handler(text,registry,error);repairs=[]
                self._save(folder/'validation.json',validation)
                validation['mechanical_metadata_completion']=repairs
                record={'model':raw.get('model',request['model']),'response_id':raw.get('id'),
                    'answer':answer,'validation':validation,'usage':usage,'input_tokens_official':count,
                    'count_latency_seconds':count_latency,'generation_latency_seconds':latency,
                    'max_output_tokens':request['max_output_tokens'],'cache_hit':False,'new_paid_generation':not reusable_raw and not bool(prior),
                    'recovered_existing_response':reusable_raw or bool(prior),
                    'recovered_from':prior['folder'] if prior else None,
                    'source_ids':list(registry),'request_sha256':fingerprint(request)}
                if self.cache_generated_results:self._save(cached,record)
            self._save(folder/'result.json',record if self.cache_generated_results else {k:v for k,v in record.items() if k!='answer'})
            self.records.append({'name':name,**record})
            self._save(self.output/'ledger.json',self.provider.ledger())
            return record
        except Exception:
            self._save(folder/'error.json',{'error':traceback.format_exc(),'answer_accepted':False})
            self._save(self.output/'ledger.json',self.provider.ledger())
            raise

    def qa(self,question,prepared,name):
        evidence=[self.compact(prepared['registry'][e['evidence_id']]) for e in prepared['evidence']];removed=[]
        while evidence:
            request=self.request(question,evidence,mode='qa',max_output_tokens=1800)
            if self.fits(request,{e['evidence_id']:prepared['registry'][e['evidence_id']] for e in evidence}):break
            removed.append(evidence.pop()['evidence_id'])
        else:raise ContextLimitError('No complete evidence item fits official token budget')
        registry={e['evidence_id']:prepared['registry'][e['evidence_id']] for e in evidence}
        self._save(self.output/name/'retrieval.json',{'hits':prepared['hits'],'kept_ids':list(registry),'removed_for_official_token_budget':removed})
        return self.call(name,request,registry)

    def _note(self,record,section):
        note={'note_id':fingerprint(record['answer'])[:16],'section':section,
                'text':record['answer']['answer_markdown'],'citations':record['answer']['citations'],
                'numeric_claims':record['answer']['numeric_claims'],'limitations':record['answer']['limitations'],
                'source_ids':record['source_ids']}
        if 'summary_sections' in record['answer']:
            note.update(supported_sections=copy_sections(record['answer']['summary_sections']),numeric_observations=[],manual_review=True)
            if record['answer'].get('evidence_status')=='manual_review':
                from ..summary_notes import anchor_sections_to_sources
                note['supported_sections']=anchor_sections_to_sources(note['supported_sections'],self.full_registry)
        if record['answer'].get('failed_validation'):
            # An unverified map/reduce output is visible in its record, but cannot
            # become trusted evidence for a later generation.
            note['text']='Original source DATA (generated note failed validation): '+canonical([self.compact(self.full_registry[key]) for key in record['source_ids']])
            note['original_prose']=[self.compact(self.full_registry[key]) for key in record['source_ids'] if self.full_registry[key].get('kind') not in ('table_facts','table_cell')]
            note['extractive_fallback']=True
        if self.retain_fact_ledger:
            note['fact_ledger']=[{'evidence_id':key,**{k:f[k] for k in ('fact_id','method','dataset','metric','comparison_methods','value')}}
                for key in record['source_ids'] for f in self.full_registry.get(key,{}).get('facts',[]) if f['metric'].lower()=='overall']
            if record['answer'].get('quality_contract'):
                payload=record['answer']['quality_contract']['payload']
                note['supported_sections']=payload['sections'];note['numeric_observations']=payload['numeric_observations']
        return note

    def _section_note(self,name,request,registry,section,notes,final=False):
        try:
            note=self._note(self.call(name,request,registry),section)
            # Carry only already validated child findings when a compression
            # drops a whole category. Never insert them into the model's answer.
            if self.retain_fact_ledger:
                from ..summary_notes import bounded_children
                note=bounded_children(note,notes)
            note['record_name']=name
            if self.cache_generated_results:self._save(self.output/name/'note.json',note)
            return note
        except (GroundingError,IncompleteResponse):
            if final:raise
            note={'note_id':'unreduced-'+fingerprint(notes)[:16],'section':section,
                'text':'Section reduction rejected. Preserve these supported child notes as source DATA: '+canonical(notes),
                'citations':[{'evidence_id':key,'pages':item['page_numbers']} for key,item in registry.items()],
                'numeric_claims':[],'limitations':['Section reduction rejected; child notes carried forward without another paid attempt.'],
                'source_ids':list(registry),'extractive_fallback':True}
            if self.cache_generated_results:self._save(self.output/name/'extractive-fallback.json',note)
            return note

    def _resume_section(self,section,notes,registry,final=False):
        if not (self.cache_generated_results and self.reuse_saved_responses and self.saved_request_setup):return None
        root=self.cache.parent/'requests'
        if not root.exists():return None
        ids=list(dict.fromkeys(key for note in notes for key in note['source_ids']))
        scope=registry if final and self.local_table_notes else {key:registry[key] for key in ids}
        prefix=section.replace(' ','-')+'-reduce-'
        for path in sorted(root.rglob('result.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            folder=path.parent
            if not folder.name.startswith(prefix) or not folder.name.endswith('-final'):continue
            try:
                old=json.loads(path.read_text(encoding='utf8'))
                if old.get('validation',{}).get('status') not in ('passed','mapped','unmapped') and not self.reuse_compatible_responses:continue
                sources=json.loads((folder/'sources.json').read_text(encoding='utf8'))
                if fingerprint(sources)!=fingerprint(scope):continue
                request=json.loads((folder/'request.json').read_text(encoding='utf8'))
                data=json.loads(request['input'][0]['content'][0]['text'])
                if data['task']!=('final_summary' if final else 'section_reduce') or data['question']!='Integrate '+section+' notes using only their supported sources.':continue
                if self._saved_artifacts(request,scope) is None:continue
            except (OSError,ValueError,KeyError,TypeError):continue
            # Revalidate the original immutable request/response, never pretend
            # it is a response to the newly compacted request.
            self.saved_request_setup(request)
            return self._section_note('summary/'+folder.name,request,scope,section,notes,final)
        return None

    def _summary_request(self,question,notes,mode,output):
        evidence=notes+self.summary_numeric_evidence if mode=='final_summary' else notes
        if mode=='final_summary' and self.summary_numeric_evidence:
            from ..table_results import summary_anchors,prose_policy
            evidence=evidence+summary_anchors(self.full_registry)+[prose_policy(self.full_registry)]
        return self.request(question,evidence,mode,output)

    def _reduce(self,notes,registry,section,final=False):
        from ..summary_notes import transport_size
        if not final or self.reuse_compatible_responses:
            resumed=self._resume_section(section,notes,registry,final)
            if resumed is not None:return resumed
        level=0;rounds=[]
        def partial(reason,current):
            self.partial_summary={'reason':reason,'notes':current}
            self._save(self.output/'summary/partial-summary.json',{'reason':reason,'available_note_count':len(current)})
            return {'partial_summary':True,'notes':current}
        while True:
            before=transport_size(notes)
            if level>=8:return partial('Reduction round limit reached',notes)
            # A section with one map note needs no extra call. Final summary always integrates.
            if len(notes)==1 and not final:return notes[0]
            mode='final_summary' if final else 'section_reduce';output=1800 if final else 1000
            groups=[];batch=[]
            for note in notes:
                candidate=batch+[note]
                request=self._summary_request('Integrate '+section+' notes using only their supported sources.',candidate,mode,output)
                if not self.fits(request) and batch:
                    groups.append(batch);batch=[note]
                else:batch=candidate
            if batch:groups.append(batch)
            if len(groups)==1:
                group=groups[0]
                ids=list(dict.fromkeys(s for n in group for s in n['source_ids']))
                request=self._summary_request('Integrate '+section+' notes using only their supported sources.',group,mode,output)
                if not self.fits(request):return partial('A bounded summary note exceeds the official request budget',notes)
                result=self._section_note(f'summary/{section.replace(" ","-")}-reduce-{level}-final',request,
                                          registry if final and self.local_table_notes else {s:registry[s] for s in ids},section,group,final)
                record=self.records[-1] if self.records else {}
                rounds.append({'section':section,'round':level,'terminal':True,'input_note_count':len(notes),'output_note_count':1,
                    'official_input_tokens':record.get('input_tokens_official'),'actual_output_tokens':record.get('usage',{}).get('output_tokens'),
                    'retained_input_bytes':before,'retained_output_bytes':transport_size([result]),
                    'retained_note_tokens':None,'token_scope':'Note-only official tokens unavailable; retained bytes are exact.'})
                self._save(self.output/f'summary/{section.replace(" ","-")}-rounds.json',rounds)
                return result
            if all(len(g)==1 for g in groups):return partial('No bounded pair fits the official request budget',notes)
            smaller=[]
            for i,group in enumerate(groups):
                if len(group)==1:smaller.append(group[0]);continue
                ids=list(dict.fromkeys(s for n in group for s in n['source_ids']))
                request=self.request('Compress '+section+' notes without losing supported findings.',group,'section_reduce',1000)
                smaller.append(self._section_note(f'summary/{section.replace(" ","-")}-reduce-{level}-{i}',request,
                                                  {s:registry[s] for s in ids},section,group))
            after=transport_size(smaller)
            stage_names={n.get('record_name') for n in smaller}
            round_records=[r for r in self.records if r['name'] in stage_names]
            rounds.append({'calls':[{'stage':r['name'],'official_input_tokens':r['input_tokens_official'],'actual_output_tokens':r.get('usage',{}).get('output_tokens')} for r in round_records],
                'retained_note_tokens':None,'token_scope':'Note-only official tokens unavailable; retained bytes are exact.',
                'section':section,'round':level,'input_note_count':len(notes),'output_note_count':len(smaller),
                'retained_input_bytes':before,'retained_output_bytes':after,'reduction_bytes':before-after,
                'measurement':'bounded UTF-8 transport bytes, not official tokens'})
            self._save(self.output/f'summary/{section.replace(" ","-")}-rounds.json',rounds)
            if after>=before:return partial('Reduction did not shrink bounded retained notes',smaller)
            notes=smaller;level+=1

    def summary(self,sources,tasks):
        registry={s['evidence_id']:s for s in sources};sections=OrderedDict();submitted=[];processed=[]
        self.full_registry=registry
        if self.summary_evidence_factory:self.summary_numeric_evidence=self.summary_evidence_factory(registry)
        for i,task in enumerate(tasks):
            ids=[s['evidence_id'] for s in task['sources']]
            processed.extend(ids)
            selected_sources=([s for s in task['sources'] if s.get('kind') not in ('table_facts','table_cell')]
                              if self.local_table_notes else task['sources'])
            if not selected_sources:
                self._save(self.output/f'summary/map-{i:03d}/local-table-ledger.json',{'source_ids':ids,
                    'reason':'Original structure retained locally; no lossy numerical map generation',
                    'new_api_calls':0})
                continue
            request=self.request('Summarize '+task['section']+' of the supplied document.',
                                 [self.compact(s) for s in selected_sources],'map',800)
            # Offline plan is conservative; still fail closed if actual official count differs.
            try:
                record=self.call(f'summary/map-{i:03d}',request,{s:registry[s] for s in ids})
                note=self._note(record,task['section'])
            except (GroundingError,IncompleteResponse):
                # Do not retry paid generation or accept a rejected paraphrase. Carry
                # original text forward explicitly so the section is not silently lost.
                note={'note_id':'extractive-'+fingerprint(ids)[:16],'section':task['section'],
                    'text':'ORIGINAL SOURCE DATA (generated map rejected by validator): '+canonical([self.compact(s) for s in task['sources']]),
                    'citations':[{'evidence_id':s,'pages':registry[s]['page_numbers']} for s in ids],
                    'numeric_claims':[],'limitations':['Generated map rejected; original source data used instead.'],
                    'source_ids':ids,'extractive_fallback':True}
                # Carry complete original excerpts as independently bounded notes.
                fallback_notes=[{**note,'note_id':note['note_id']+'-'+source['evidence_id'],
                    'source_ids':[source['evidence_id']],
                    'original_prose':[self.compact(source)]} for source in selected_sources]
                if self.cache_generated_results:self._save(self.output/f'summary/map-{i:03d}/extractive-fallback.json',note)
            if self.cache_generated_results:self._save(self.output/f'summary/map-{i:03d}/note.json',note)
            submitted.extend(s['evidence_id'] for s in selected_sources)
            sections.setdefault(task['section'],[]).extend(fallback_notes if note.get('extractive_fallback') and 'original_prose' not in note else [note])
            print(f'Summary segment {i+1}/{len(tasks)} processed; extractive fallback={note.get("extractive_fallback",False)}',flush=True)
        assert set(processed)==set(registry)
        if not sections:raise ValueError('Summary requires narrative sources; this document only contains untyped or table-only evidence.')
        section_notes=[]
        for section,notes in sections.items():
            reduced=self._reduce(notes,registry,section)
            section_notes.extend(reduced['notes'] if reduced.get('partial_summary') else [reduced])
        if not self.include_ancillary:
            import re
            def ancillary(note):
                paths=[' / '.join(registry[key].get('section_path',[])) for key in note['source_ids'] if key in registry]
                return bool(re.search(r'references|bibliograph|appendi|參考文獻|附錄',note.get('section',''),re.I) or paths and all(re.search(r'references|bibliograph|appendi|參考文獻|附錄',path,re.I) for path in paths))
            section_notes.sort(key=ancillary)
        final=self._reduce(section_notes,registry,'Whole document',final=True)
        coverage={'source_units_submitted':len(set(submitted)),'source_units_total':len(registry),
            'all_source_units_submitted':set(submitted)==set(registry),'sections':list(sections),
            'all_source_units_processed':set(processed)==set(registry),
            'note':'Input coverage only; faithful inclusion and important omissions need human review.'}
        self._save(self.output/'summary/coverage.json',coverage)
        return final
