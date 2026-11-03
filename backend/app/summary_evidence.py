"""Bounded, source-linked original table groups for final summary input."""
import copy
import re
from collections import defaultdict
from .numeric_context import reliable
from .table_comparisons import comparison_reports
from .rag.core import canonical


def representative_tables(registry,max_bytes=4200):
    tables=defaultdict(dict);origins={};invalid=set()
    for source_id,source in registry.items():
        for fact in source.get('facts',[]):
            if not isinstance(fact,dict):continue
            table=fact.get('table_id')
            if not table:continue
            if any(not isinstance(fact.get(field),str) for field in ('dataset','metric','method','value')) or not isinstance(fact.get('comparison_methods'),list) or not all(isinstance(method,str) for method in fact['comparison_methods']):
                invalid.add(table);continue
            key=(fact['dataset'],fact['metric'],tuple(sorted(fact['comparison_methods'])),fact['method'])
            prior=tables[table].get(key)
            if prior and prior['value']!=fact['value']:
                tables[table][key]={**fact,'value':'AMBIGUOUS'}
            elif prior is None:
                tables[table][key]=fact;origins[(table,key)]=source_id
    usable={key:list(rows.values()) for key,rows in tables.items() if key not in invalid and reliable(list(rows.values()))}
    if not usable:return []
    quota=max(0,(max_bytes-2)//len(usable)-1);output=[]
    for table,facts in sorted(usable.items()):
        preferred={}
        for report in comparison_reports(facts):
            for series in report['direct_patterns']:
                highlights=series['exceptions_to_majority'] or [series[key][0] for key in ('higher','lower','equal') if series[key]]
                if sum(bool(series[key]) for key in ('higher','lower','equal'))<2:continue
                for dataset in report['direct_pairs']:
                    d,left,_,_,right,_=dataset
                    if {left,right}!={series['left'],series['right']}:continue
                    preferred[(d,report['metric'],tuple(sorted((left,right))))]=-2 if d in series['exceptions_to_majority'] else 0 if d in highlights else 1
            cross=report['cross_group_observations']
            if cross:
                ref=cross['common_reference']
                for series in cross['patterns']:
                    highlights=series['exceptions_to_majority'] or [series[key][0] for key in ('higher','lower','equal') if series[key]]
                    for dataset in highlights:
                        for candidate in (series['left'],series['right']):
                            key=(dataset,report['metric'],tuple(sorted((ref,candidate))))
                            preferred[key]=min(preferred.get(key,2),0)
        groups=defaultdict(list)
        for fact in facts:groups[(fact['dataset'],fact['metric'],tuple(sorted(fact['comparison_methods'])))].append(fact)
        # Preserve a compact primary-metric ordering across common-reference
        # groups, including exceptions, instead of asking the model to infer it
        # from a small selection of unrelated paired rows.
        rate_orderings=[]
        ablation=any(any(f.get('table_id')==table for f in source.get('facts',[])) and re.search(r'ablat|\u6d88\u878d',' '.join(source.get('section_path',[]))+' '+source.get('text',''),re.I) for source in registry.values())
        cross_reports=[r for r in comparison_reports(facts) if r['cross_group_observations']] if ablation else []
        if cross_reports:
            report=next((r for r in cross_reports if r['metric'].casefold()=='overall'),cross_reports[0])
            cross=report['cross_group_observations'];reference=cross['common_reference']
            for ranking in cross['rankings']:
                rates=[]
                for rate in ranking['rates']:
                    key=(ranking['dataset'],report['metric'],tuple(sorted((reference,rate['method']))),rate['method'])
                    rates.append({'method':rate['method'],'value':rate['value'],'evidence_id':origins[(table,key)]})
                rate_orderings.append({'dataset':ranking['dataset'],'metric':report['metric'],'paired_reference':reference,'descending_reported_rates':rates})
        ordering_meta=({'reported_rate_orderings':rate_orderings,
            'ordering_scope':'Exact reported rates against a common reference; not direct head-to-head or causal comparisons.'} if rate_orderings else {})
        selected=[]
        def priority(key):
            dataset,metric,pair=key
            return (preferred.get(key,2),metric.casefold()!='overall',dataset,pair,metric)
        for key,rows in sorted(groups.items(),key=lambda item:priority(item[0])):
            group=[]
            for fact in rows:
                original_key=(fact['dataset'],fact['metric'],tuple(sorted(fact['comparison_methods'])),fact['method'])
                group.append({'evidence_id':origins[(table,original_key)],**{field:copy.deepcopy(fact[field]) for field in ('method','dataset','metric','value','comparison_methods')}})
            item={'source_type':'structured_table_summary','table_id':table,'table_number':rows[0].get('table_number'),
                'table_facts':selected+group,'selection_scope':'Representative complete groups, not exhaustive. Original tables remain available; absence here is not missing PDF input.',**ordering_meta}
            if len(canonical(item).encode('utf8'))<=quota:selected+=group
        if selected:
            item['table_facts']=selected
            # Keep the exact quota, including any final metadata, rather than
            # appending an unbounded ledger to every reduce note.
            item.pop('omitted_groups',None)
            output.append(item)
    return output
