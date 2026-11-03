"""Narrow checks of literal value ordering, never a general entailment judge."""
import re
from collections import defaultdict
from .core import GroundingError,number


def check_comparison_directions(sections,registry):
    facts={f['fact_id']:f for source in registry.values() for f in source.get('facts',[])}
    methods=sorted({f['method'] for f in facts.values()},key=len,reverse=True)
    metrics=sorted({f['metric'] for f in facts.values()},key=len,reverse=True)
    datasets=sorted({f['dataset'] for f in facts.values()},key=len,reverse=True)
    def alternatives(values):return '(?:'+'|'.join(re.escape(v) for v in values)+')'
    patterns=[]
    if methods and metrics and datasets:
        method=alternatives(methods);metric=alternatives(metrics);dataset=alternatives(datasets)
        # Full-sentence matching excludes negation, attribution, conditions,
        # multiple claims, and "better"/"outperforms" (metric orientation unknown).
        patterns=[re.compile(
            r'(?P<left>'+method+r') (?:has |shows |reports )?(?:a |an )?'
            r'(?P<relation>higher|lower|equal) (?P<metric>'+metric+r') '
            r'(?:values?|rates?|scores?) (?:than|to|as) (?P<right>'+method+r') '
            r'on (?P<dataset>'+dataset+r')[.!]?',re.I),
            re.compile(r'(?P<left>'+method+r') is (?P<relation>higher|lower|equal) '
            r'(?:than|to|as) (?P<right>'+method+r') on (?P<dataset>'+dataset+r') '
            r'for (?P<metric>'+metric+r')[.!]?',re.I)]
    reports=[]
    for section in sections:
        for statement in section['statements']:
            text=statement['text'].strip()
            match=next((m for p in patterns if (m:=p.fullmatch(text))),None)
            report={'text':text,'status':'not_evaluable',
                'reason':'No unambiguous supported literal-value comparison; semantic review required.'}
            if match:
                fields=match.groupdict();groups=defaultdict(dict)
                for fact in facts.values():
                    if fact['metric'].casefold()!=fields['metric'].casefold() or fact['dataset'].casefold()!=fields['dataset'].casefold():continue
                    pair={m.casefold() for m in fact['comparison_methods']}
                    if not {fields['left'].casefold(),fields['right'].casefold()}.issubset(pair):continue
                    key=(fact['table_id'],fact['dataset'],fact['metric'],tuple(fact['comparison_methods']))
                    groups[key].setdefault(fact['method'].casefold(),[]).append(fact)
                complete=[]
                for key,group in groups.items():
                    if not all(len(group.get(m.casefold(),[]))==1 for m in key[3]):continue
                    left=group[fields['left'].casefold()][0];right=group[fields['right'].casefold()][0]
                    a=number(left['value']);b=number(right['value'])
                    if a is None or b is None or not a.is_finite() or not b.is_finite():continue
                    if ('%' in left['value'])!=('%' in right['value']):continue
                    complete.append((left,right,a,b))
                if len(complete)==1:
                    left,right,a,b=complete[0]
                    actual='higher' if a>b else 'lower' if a<b else 'equal'
                    if actual!=fields['relation'].lower():
                        raise GroundingError('Comparison direction contradicts supplied structured values: '+text)
                    report={'text':text,'status':'consistent_with_structured_values',
                        'scope':'Literal value ordering only, not superiority, causality or quote entailment.',
                        'fact_ids':[left['fact_id'],right['fact_id']]}
                else:report['reason']='Structured comparison scope is missing, incomplete or ambiguous.'
            reports.append(report)
    return {'statements':reports,'checked':sum(r['status']=='consistent_with_structured_values' for r in reports),
        'unverified':sum(r['status']=='not_evaluable' for r in reports),
        'semantic_fidelity':'pending_manual_review'}
