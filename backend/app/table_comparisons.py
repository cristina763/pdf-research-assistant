"""Bounded pre-generation arithmetic over reliable existing fact tuples."""
import copy
from collections import defaultdict,Counter
from decimal import Decimal
from itertools import combinations
from .numeric_context import reliable
from .rag.core import canonical


def number(value):return Decimal(value.rstrip('%').replace(',',''))
def relation(left,right):return '>' if number(left)>number(right) else '<' if number(left)<number(right) else '='


def pattern(left,right,observations,datasets,kind):
    buckets={symbol:[d for d,a,b in observations if relation(a,b)==symbol] for symbol in ('>','<','=')}
    counts=Counter({symbol:len(values) for symbol,values in buckets.items()})
    majority=next((symbol for symbol,count in counts.items() if count>len(observations)/2),None)
    return {'left':left,'right':right,'kind':kind,'higher':buckets['>'],'lower':buckets['<'],'equal':buckets['='],
        'missing_datasets':sorted(set(datasets)-{d for d,_,_ in observations}),
        'majority_relation':majority,'exceptions_to_majority':[d for d,a,b in observations if majority and relation(a,b)!=majority]}


def comparison_reports(facts):
    """All relations are numerical ordering, not causality or metric utility."""
    if not reliable(facts):return []
    tables=defaultdict(list)
    for fact in facts:tables[(fact.get('table_id'),fact['metric'])].append(fact)
    reports=[]
    for (table,metric),rows in sorted(tables.items(),key=lambda item:(item[0][1].casefold()!='overall',str(item[0]))):
        groups=defaultdict(dict)
        for row in rows:groups[(row['dataset'],tuple(sorted(row['comparison_methods'])))][row['method']]=row['value']
        datasets=sorted({row['dataset'] for row in rows});direct=[];series=defaultdict(list)
        for (dataset,group),values in sorted(groups.items()):
            if len(group)!=2:continue  # No invented head-to-head interpretation for multi-arm groups.
            left,right=group
            direct.append([dataset,left,values[left],relation(values[left],values[right]),right,values[right]])
            a,b=sorted(group);series[(a,b)].append((dataset,values[a],values[b]))
        report={'table_id':table,'metric':metric,
            'direct_columns':['dataset','left','left_value','relation','right','right_value'],
            'direct_pairs':direct,'direct_patterns':[pattern(a,b,obs,datasets,'same_comparison_group') for (a,b),obs in sorted(series.items())],
            'cross_group_observations':[]}
        pairs={group for _,group in groups if len(group)==2}
        reference=set.intersection(*(set(group) for group in pairs)) if len(pairs)>1 else set()
        if len(reference)==1:
            ref=next(iter(reference));by_dataset=defaultdict(dict)
            for (dataset,group),values in groups.items():
                if len(group)!=2 or ref not in group:continue
                candidate=next(method for method in group if method!=ref)
                by_dataset[dataset][candidate]=values[candidate]
            rankings=[];cross=defaultdict(list)
            for dataset,values in sorted(by_dataset.items()):
                if len({value.endswith('%') for value in values.values()})!=1:continue
                ranks={value:index+1 for index,value in enumerate(sorted({number(v) for v in values.values()},reverse=True))}
                rankings.append({'dataset':dataset,'rates':[{'method':m,'value':v,'rank':ranks[number(v)]} for m,v in sorted(values.items(),key=lambda item:(-number(item[1]),item[0]))]})
                for left,right in combinations(sorted(values),2):cross[(left,right)].append((dataset,values[left],values[right]))
            report['cross_group_observations']={'common_reference':ref,'kind':'reported_values_against_common_reference_not_head_to_head_or_before_after',
                'rankings':rankings,'patterns':[pattern(a,b,obs,datasets,'cross_group_numeric_observation') for (a,b),obs in sorted(cross.items())]}
        # Rankings/direct pairs already encode uniform ordering. Spend the small
        # transport allowance on mixed-direction and incomplete-coverage cases.
        report['direct_patterns']=[p for p in report['direct_patterns'] if p['exceptions_to_majority'] or p['missing_datasets'] or sum(bool(p[key]) for key in ('higher','lower','equal'))>1]
        if report['cross_group_observations']:
            cross=report['cross_group_observations']
            cross['patterns']=[p for p in cross['patterns'] if p['exceptions_to_majority'] or p['missing_datasets'] or sum(bool(p[key]) for key in ('higher','lower','equal'))>1]
        reports.append(report)
    reports.sort(key=lambda report:(report['metric'].casefold()!='overall',not bool(report['direct_patterns']),str(report['table_id']),report['metric']))
    return reports


def attach_comparisons(evidence,max_bytes=4000):
    """The budget caps only derived observations, never original facts or prose."""
    remaining=max_bytes
    for item in evidence:
        facts=item.get('table_facts',[])
        if not facts or not reliable(facts):continue
        scope=item.get('numeric_scope',{})
        if len(scope.get('table_ids',[]))>1:
            item['numeric_evidence_warning']='Multiple table scopes; no derived comparison supplied.';continue
        rows=copy.deepcopy(facts)
        for fact in rows:fact.setdefault('table_id',next(iter(scope.get('table_ids',[])),item['evidence_id']))
        retained=[];omitted=[]
        def payload():
            return {'source_id':item['evidence_id'],'scope':'Numeric order only; no causal, temporal or metric-utility claim.',
                'reports':retained,'omitted_metrics_due_to_capacity':omitted,
                'method_label_rule':'Method names are literal identifiers; preserve leading minus signs exactly.'}
        for report in comparison_reports(rows):
            retained.append(report)
            if len(canonical(payload()).encode('utf8'))>remaining:
                retained.pop();omitted.append(report['metric'])
        while retained and len(canonical(payload()).encode('utf8'))>remaining:
            omitted.append(retained.pop()['metric'])
        if retained:
            item['computed_comparisons']=payload()
            remaining-=len(canonical(payload()).encode('utf8'))
    return evidence
