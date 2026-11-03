"""Small parent-evidence extension. BM25 and historical assembly stay unchanged."""
import copy
import json
from pathlib import Path

from .context import ContextAssembler,fact_text
from .retrieval import tokenize

class EnhancedAssembler(ContextAssembler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.chunk_sources={}
        for c in self.chunks.values():
            for source in c['source_refs']:self.chunk_sources.setdefault(source,[]).append(c['chunk_id'])

    def _origin_ids(self,entry):
        if entry['chunk_id'] in self.chunks:return [entry['chunk_id']]
        return list(dict.fromkeys(k for r in entry['source_refs'] for k in self.chunk_sources.get(r,[])))

    def _render(self,entries):
        pieces=[]
        for i,e in enumerate(entries,1):
            e['evidence_id']=f'C{i}'
            ids=','.join(e['origin_chunk_ids'])
            citation=f'[C{i} | PDF pages {e["page_numbers"]} | chunks {ids}]'
            e['text']=citation+'\n'+e['_payload']
            pieces.append(e['text'])
        return '\n\n'.join(pieces)

    def assemble(self,hits,query=None):
        baseline=super().assemble(hits)
        entries=[];groups={}
        protected={fid for e in baseline['evidence'] for fid in e['fact_ids']}
        for original in baseline['evidence']:
            e=copy.deepcopy(original);e['origin_chunk_ids']=self._origin_ids(e)
            e['_payload']=e['text'].split('\n',1)[1]
            if e['fact_ids']:
                table_id=e['parent_table_id']
                if table_id in groups:
                    group=groups[table_id]
                    group['fact_ids']=list(dict.fromkeys(group['fact_ids']+e['fact_ids']))
                    group['origin_chunk_ids']=list(dict.fromkeys(group['origin_chunk_ids']+e['origin_chunk_ids']))
                    group['source_refs']=sorted(set(group['source_refs']+e['source_refs']))
                    group['page_numbers']=sorted(set(group['page_numbers']+e['page_numbers']))
                    group['provenance']=[json.loads(v) for v in sorted({json.dumps(p,sort_keys=True) for p in group['provenance']+e['provenance']})]
                else:
                    groups[table_id]=e;entries.append(e)
            else:entries.append(e)
        for table_id,e in groups.items():
            table=self.tables[table_id]
            e['comparison_groups']=list(dict.fromkeys(' vs '.join(self.facts[f]['comparison_methods']) for f in e['fact_ids']))
            e['_payload']='Section: '+' / '.join(table['section_path'])+'\n'+'\n'.join(table['captions'])+'\n'+\
                '\n'.join(fact_text(self.facts[f]) for f in e['fact_ids'])
        context=self._render(entries)
        if self.counter(context)>self.budget:
            baseline['enhancement']={'status':'baseline_fallback','reason':'Lossless rebundling exceeds budget'}
            return baseline
        represented={ref for e in entries for ref in e['source_refs']}
        supplements=[];qterms=set(tokenize(query or ''))
        table_hits=list(dict.fromkeys(self.chunks[h['chunk_id']].get('table_id') for h in hits if self.chunks[h['chunk_id']].get('table_id')))
        for table_id in table_hits:
            table=self.tables[table_id]
            if not any(e.get('parent_table_id')==table_id for e in entries):continue
            candidates=[e for e in self.section_body if e['section_path']==table['section_path']
                        and any(abs(p-tp)<=1 for p in e['page_numbers'] for tp in table['page_numbers'])]
            # Generic lexical relevance, source-page proximity, then document order.
            candidates=sorted(enumerate(candidates),key=lambda pair:(
                -len(qterms.intersection(tokenize(pair[1]['text']))),
                min(abs(p-tp) for p in pair[1]['page_numbers'] for tp in table['page_numbers']),pair[0]))
            existing=sum(e.get('parent_table_id')==table_id and not e['fact_ids'] for e in entries)
            for _,body in candidates:
                if existing>=2:break
                if body['source_ref'] in represented:continue
                if self.counter(body['text'])>1600:continue  # Complete paragraphs only, never truncate numbers.
                origins=self.chunk_sources.get(body['source_ref'],[])
                if not origins:continue
                e={'chunk_id':origins[0],'origin_chunk_ids':origins,'fact_ids':[],
                   'source_refs':[body['source_ref']],'page_numbers':body['page_numbers'],
                   'section_path':body['section_path'],'parent_table_id':table_id,
                   'derived_from_chunk_ids':[h['chunk_id'] for h in hits if self.chunks[h['chunk_id']].get('table_id')==table_id],
                   'provenance':[{'source_ref':body['source_ref'],**p} for p in body['provenance']],
                   'trust':'same_section_nearby_page_original_paragraph; human_ground_truth_pending',
                   '_payload':'Section: '+' / '.join(body['section_path'])+'\n'+body['text']}
                proposed=self._render(entries+[e])
                if self.counter(proposed)>self.budget:continue
                entries.append(e);represented.add(body['source_ref']);supplements.append(body['source_ref']);existing+=1
        context=self._render(entries)
        assert protected.issubset({f for e in entries for f in e['fact_ids']})
        assert self.counter(context)<=self.budget
        for e in entries:
            assert e['origin_chunk_ids'] and all(i in self.chunks for i in e['origin_chunk_ids'])
            del e['_payload']
        return {**baseline,'context':context,'evidence':entries,'count':self.counter(context),
                'enhancement':{'status':'applied','additional_body_source_refs':supplements,
                               'baseline_fact_ids_preserved':True,'no_additional_numeric_facts_inferred':True,
                               'policy':'Lossless table bundle; up to two whole same-section nearby-page paragraphs; lexical relevance and page proximity, no question-specific routing'}}
