"""Comparison expansion over existing structures, without changing BM25 rankings."""
import copy
import re
from collections import Counter

from .enhanced_context import EnhancedAssembler
from .retrieval import tokenize


class ComparisonAssembler(EnhancedAssembler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.body=[e for e in self.document['elements'] if e['content_type'] in ('text','list_item') and e['text'].strip()]

    def assemble(self,hits,query=None):
        baseline=super().assemble(hits,query=query)
        if not re.search(r'compar|\bvs\b|versus|ablat|variants?|versions?',query or '',re.I):return baseline
        q=(query or '').lower();terms=set(tokenize(q));ablation=bool(re.search('ablat',q))
        known={f['method'] for f in self.facts.values()}
        named={m for m in known if re.search(r'(?<!\w)'+re.escape(m.lower())+r'(?!\w)',q)}
        candidates=[t for t in self.tables.values() if t['facts']]
        if not candidates:return baseline
        def table_score(t):
            methods={f['method'] for f in t['facts']}
            return (len(methods & named),int(ablation and any(m.startswith('-') for m in methods)),
                    len(terms & set(tokenize(' '.join(t['captions']+t['section_path'])))))
        table=max(candidates,key=table_score)
        methods={f['method'] for f in table['facts']}
        selected_methods=(methods if ablation else named & methods)
        metrics={f['metric'] for f in table['facts']}
        requested_metrics={m for m in metrics if m.lower() in q}
        default_metric=next((m for m in metrics if m.lower()=='overall'),sorted(metrics)[0])
        chosen_metrics=requested_metrics or {default_metric}
        # A group is atomic: select both sides for every selected dataset/metric.
        groups={tuple(f['comparison_methods']) for f in table['facts']
                if selected_methods.issubset(set(f['comparison_methods']))}
        if ablation:groups={tuple(f['comparison_methods']) for f in table['facts']}
        selected=[f for f in table['facts'] if tuple(f['comparison_methods']) in groups and f['metric'] in chosen_metrics]
        protected={fid for e in baseline['evidence'] for fid in e['fact_ids']}
        # Preserve old facts; close their groups as well, rather than discarding a
        # previously validated cell to make the new comparison look better.
        protected_keys={(self.facts[f]['dataset'],self.facts[f]['metric'],tuple(self.facts[f]['comparison_methods']))
                        for f in protected if self.facts[f]['table_id']==table['table_id']}
        selected_ids={f['fact_id'] for f in selected}
        selected_ids.update(f['fact_id'] for f in table['facts'] if (f['dataset'],f['metric'],tuple(f['comparison_methods'])) in protected_keys)
        entries=[]
        def add_body(e,role):
            origins=self.chunk_sources.get(e['source_ref'],[])
            if not origins or any(e['source_ref'] in x['source_refs'] for x in entries):return
            entries.append({'chunk_id':origins[0],'origin_chunk_ids':origins,'source_refs':[e['source_ref']],
                'page_numbers':e['page_numbers'],'section_path':e['section_path'],'provenance':e['provenance'],
                'text':e['text'],'fact_ids':[],'parent_table_id':None,'trust':'original_parsed_prose; human_verification_pending',
                'coverage_role':role})
        if selected_ids:
            origins=[c['chunk_id'] for c in self.chunks.values() if selected_ids.intersection(c.get('fact_ids',[]))]
            entries.append({'chunk_id':origins[0],'origin_chunk_ids':origins,'source_refs':[table['source_ref']]+table['caption_refs'],
                'page_numbers':table['page_numbers'],'section_path':table['section_path'],'provenance':table['provenance'],
                'text':' / '.join(table['captions']),'fact_ids':[f['fact_id'] for f in table['facts'] if f['fact_id'] in selected_ids],
                'parent_table_id':table['table_id'],'trust':'native_structure_validated; human_verification_pending',
                'required_methods':sorted(selected_methods),'coverage_role':'performance'})
        # Table-local interpretation includes list items and whole paragraphs.
        for e in self.body:
            if e['section_path']==table['section_path']:add_body(e,'interpretation')
        if not ablation:
            # Cross-section comparison prose: require both named entities. It can
            # describe methods, cost or updates without relying on table proximity.
            relevant=[e for e in self.body if len(named)>=2 and all(m.lower() in e['text'].lower() for m in named)]
            for role,pattern in [('method',r'retriev|index|architect|mechanism'),('cost',r'cost|token|api call|overhead|update')]:
                ranked=sorted((e for e in relevant if re.search(pattern,e['text'],re.I)),
                    key=lambda e:(-int(role=='cost' and bool(re.search(r'cost|adaptability|complexity',' '.join(e['section_path']),re.I))),
                                  -len(terms & set(tokenize(e['text']))),e['page_numbers'][0]))
                for e in ranked[:3]:add_body(e,role)
            # A comparison also needs each system's own definition. Requiring
            # both names in one paragraph silently excluded baseline mechanisms.
            for method in sorted(named):
                definitions=[e for e in self.body if re.match(re.escape(method)+r'\s*(?:\(|:)',e['text'],re.I)
                    and re.search(r'retriev|index|graph|architect',e['text'],re.I)]
                for e in definitions[:1]:add_body(e,'method_definition')
                sections={tuple(e['section_path']) for e in self.body
                    if re.search(r'(?<!\w)'+re.escape(method)+r'(?!\w)',e['text'],re.I)
                    and re.search(r'retriev|index|architect|framework|approach',' '.join(e['section_path']),re.I)
                    and not re.search(r'evaluat|compar|cost|related work',' '.join(e['section_path']),re.I)}
                details=[e for e in self.body if tuple(e['section_path']) in sections
                    and re.search(r'keyword matching|low.level retrieval|high.level retrieval|entity and relationship extraction',e['text'],re.I)]
                details.sort(key=lambda e:(-int(bool(re.match(r'(?:\(?ii\)?[.)]?\s*)?Keyword Matching|Low.Level Retrieval|High.Level Retrieval',e['text'],re.I))),e['page_numbers'][0]))
                for e in details[:4]:add_body(e,'method_detail')
        for old in baseline['evidence']:
            if not old['fact_ids']:continue
            remaining=[f for f in old['fact_ids'] if f not in selected_ids]
            if remaining:
                e=copy.deepcopy(old);e['fact_ids']=remaining
                e['origin_chunk_ids']=self._origin_ids(e);entries.append(e)
        refs={ref for e in entries for ref in e['source_refs']}
        # Cross-reference existence and semantic location are separate checks.
        crossrefs=[]
        for e in entries:
            if e['fact_ids']:continue
            for kind,num in re.findall(r'\b(Table|Figure)\s+(\d+)',e['text']):
                if kind=='Table':
                    targets=[t for t in self.tables.values() if any(re.match(r'Table\s+'+num+r'\b',cap) for cap in t['captions'])]
                    same=any(t['section_path']==e['section_path'] for t in targets)
                    crossrefs.append({'source_refs':e['source_refs'],'reference':kind+' '+num,
                        'target_pages':[t['page_numbers'] for t in targets],
                        'status':'same_section_target' if same else 'cross_section_reference_requires_manual_check'})
        for i,e in enumerate(entries,1):e['evidence_id']=f'C{i}'
        for e in entries:
            warnings=[r for r in crossrefs if r['source_refs']==e['source_refs'] and r['status']!='same_section_target']
            if warnings:e['cross_reference_warnings']=warnings
        assert protected.issubset({f for e in entries for f in e['fact_ids']})
        context='\n\n'.join(e['text'] for e in entries)
        # Count the returned text, not the superseded EnhancedAssembler draft.
        # This remains the injected counter's unit; structured payload/schema
        # are counted separately at Generator's official API boundary.
        return {**baseline,'evidence':entries,'context':context,'count':self.counter(context),
            'comparison_expansion':{'selected_table':table['table_id'],'required_methods':sorted(selected_methods),
                'selected_metrics':sorted(chosen_metrics),'complete_groups':True,'baseline_facts_preserved':True,
                'body_types':['text','list_item'],'cross_reference_audit':crossrefs,
                'final_token_check':'official count required; byte draft is not a final context limit'}}
