"""QA-only scoped views of existing typed facts; never a result validator."""
import copy
import re
from collections import defaultdict
from decimal import Decimal,InvalidOperation

REVISION='scoped-numeric-qa-v2'
INTENT=re.compile(r'\b(?:compar\w*|versus|vs|rates?|values?|scores?|percent\w*|highest|lowest|largest|smallest|best|worst|rank\w*|performance|results?|ablat\w*|how many|how much)\b|數值|數據|比較|最高|最低|排名|消融|結果|表現',re.I)
RANK=re.compile(r'\b(?:highest|lowest|largest|smallest|best|worst|rank\w*)\b|最高|最低|排名',re.I)

def named(question,label):
    return bool(re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',question,re.I))


def reliable(facts):
    """Only complete, unambiguous supplied groups qualify for narrowing."""
    groups=defaultdict(dict)
    for fact in facts:
        if not isinstance(fact,dict) or any(not isinstance(fact.get(k),str) or not fact[k] for k in ('method','dataset','metric','value')):return False
        pair=fact.get('comparison_methods')
        if not isinstance(pair,list) or len(pair)<2 or not all(isinstance(m,str) for m in pair) or len(set(pair))!=len(pair) or fact['method'] not in pair:return False
        try:
            value=Decimal(fact['value'].rstrip('%').replace(',',''))
            if not value.is_finite():return False
        except InvalidOperation:return False
        key=(fact.get('table_id'),fact['dataset'],fact['metric'],tuple(sorted(pair)))
        entry=(fact['value'],fact['value'].endswith('%'))
        prior=groups[key].get(fact['method'])
        if prior is not None and prior!=entry:return False
        groups[key][fact['method']]=entry
    return bool(groups) and all(set(group)==set(key[3]) and len({v[1] for v in group.values()})==1 for key,group in groups.items())


def scoped_evidence(question,evidence):
    if not INTENT.search(question):return evidence,False
    result=copy.deepcopy(evidence)
    tables=[item for item in result if item.get('table_facts')]
    if not tables:return result,True
    metrics={fact['metric'] for item in tables for fact in item['table_facts'] if isinstance(fact,dict) and isinstance(fact.get('metric'),str)}
    datasets={fact['dataset'] for item in tables for fact in item['table_facts'] if isinstance(fact,dict) and isinstance(fact.get('dataset'),str)}
    methods={fact['method'] for item in tables for fact in item['table_facts'] if isinstance(fact,dict) and isinstance(fact.get('method'),str)}
    requested_metrics={m for m in metrics if named(question,m)}
    requested_datasets={d for d in datasets if named(question,d)}
    requested_methods={m for m in methods if named(question,m)}
    ablation=bool(re.search(r'ablat|消融',question,re.I))
    ranking=bool(RANK.search(question))
    explicit_table=re.search(r'\btable\s+(\d+)\b|表\s*(\d+)',question,re.I)
    selected=None
    candidates=[item for item in tables if reliable(item['table_facts'])]
    if explicit_table:
        number=int(next(group for group in explicit_table.groups() if group))
        matches=[item for item in candidates if {f.get('table_number') for f in item['table_facts']}=={number}]
        if len(matches)==1:selected=matches[0]['evidence_id']
    elif ranking and ablation:
        # A section/caption explicitly labelled as ablation disambiguates table
        # scope. Otherwise retain separate tables and state the ambiguity.
        matches=[item for item in candidates if re.search(r'ablat|消融',' '.join(item.get('section',[]))+' '+item.get('text',''),re.I)]
        if len(matches)==1:selected=matches[0]['evidence_id']
    filtered=[]
    for item in result:
        facts=item.get('table_facts')
        if not facts:
            filtered.append(item);continue  # Never trim narrative evidence.
        if selected is not None and item['evidence_id']!=selected:continue
        if not reliable(facts):
            item['numeric_evidence_warning']='Typed fields are incomplete/conflicting; original supplied evidence retained. Do not infer values or rankings.'
            filtered.append(item);continue
        rows=[f for f in facts if (not requested_metrics or f['metric'] in requested_metrics) and (not requested_datasets or f['dataset'] in requested_datasets)]
        if requested_methods and not ranking and not ablation:
            direct=[f for f in rows if requested_methods.issubset(set(f['comparison_methods']))]
            if direct:rows=direct
            else:
                referenced=[f for f in rows if requested_methods.intersection(f['comparison_methods'])]
                if referenced:rows=referenced
                item['numeric_evidence_warning']='No supplied direct comparison covers all named methods. Keep reference groups separate; do not turn common-reference rates into head-to-head results.'
        if not rows:
            # An explicit scope with no matches is absence, not a licence to use
            # a nearby dataset or metric. Its raw source remains in local storage.
            item['table_facts']=[]
            item['numeric_evidence_warning']='No supplied typed facts match the requested dataset/metric. Use the original PDF for review; do not substitute other cells.'
            filtered.append(item);continue
        seen=set();compact=[]
        for fact in rows:
            key=(fact.get('table_id'),fact['dataset'],fact['metric'],tuple(fact['comparison_methods']),fact['method'])
            if key in seen:continue
            seen.add(key)
            compact.append({k:copy.deepcopy(fact[k]) for k in ('fact_id','method','dataset','metric','value','comparison_methods') if k in fact})
        item['table_facts']=compact
        item['numeric_scope']={'source_id':item['evidence_id'],'table_ids':sorted({str(f.get('table_id',item['evidence_id'])) for f in rows}),
            'table_numbers':sorted({f['table_number'] for f in rows if isinstance(f.get('table_number'),int)}),
            'datasets':sorted({f['dataset'] for f in rows}),'metrics':sorted({f['metric'] for f in rows}),
            'rule':'Each comparison_methods group is atomic; both reference and candidate values retained. Rows from separate tables/groups are not direct head-to-head comparisons.'}
        filtered.append(item)
    from .table_comparisons import attach_comparisons
    return attach_comparisons(filtered),True


def enrich_method_comparison(question,prepared,document):
    """Use already parsed facts for all metrics in a broad named-method comparison.

    Retrieval order, narrative evidence and original artifacts remain unchanged.
    Explicit metric questions keep their current narrow evidence selection.
    """
    ablation=bool(re.search(r'ablat|\u6d88\u878d',question,re.I))
    if not ablation and not re.search(r'compar|versus|\bvs\b|比較',question,re.I):return prepared
    native={table['table_id']:table for table in document.get('tables',[])}
    result=copy.deepcopy(prepared)
    for source in result['registry'].values():
        table_id=source.get('parent_table_id') or source.get('table_id')
        table=native.get(table_id)
        if not table or not reliable(table.get('facts',[])):continue
        facts=table['facts'];metrics={f['metric'] for f in facts}
        if any(named(question,metric) for metric in metrics):continue
        methods={f['method'] for f in facts};requested={m for m in methods if named(question,m)}
        if ablation:
            # Expand only the already retrieved ablation table.
            if not re.search(r'ablat|\u6d88\u878d',' '.join(table.get('section_path',[])+table.get('captions',[])),re.I):continue
        else:
            if len(requested)<2:continue
            if not any(requested.issubset(set(f['comparison_methods'])) for f in facts):continue
        source['facts']=copy.deepcopy(facts)
    return result

QA_NUMERIC_GUIDANCE='''
NUMERICAL QA: computed_comparisons is deterministic arithmetic DATA, not PDF prose. Use its dataset-by-dataset relations, rankings, ties and exception lists; do not contradict them. Cross-group rankings are reported-rate observations, NOT direct contests and NEVER before/after changes. Preserve literal method labels including leading minus signs; use inline code for such labels.
Use supplied typed facts for numerical claims. A grouped table uses table_fact_groups: comparison_methods identifies each pair, columns labels every cell in rows, and all original values remain in the labelled rows. Decode the full pair and metric before comparing. An omitted_metrics_due_to_capacity entry concerns derived arithmetic only, not the availability of original table rows. Match table/source ID, comparison_methods, dataset, metric and method before quoting a value.
For maximum/minimum or rankings, enumerate all relevant candidates within the requested scope and check ties. A full model is not automatically the best variant.
Before saying all/every/always, higher/lower or superior, compare every requested dataset/group and explicitly report exceptions. Qualitative prose does not override the numerical table.
For a method comparison, cover technique differences, experimental outcomes and exceptions, plus source-supported indexing/retrieval costs and incremental-update mechanisms when supplied. Do not replace those explanations with a numeric list. Keep cost/update claims tied to the supplied experimental setting, not universal benchmarks.
For ablations, explain what each variant removes using the supplied descriptions, not guesses from its label, and describe its observed effect. A paired reference is not automatically the unmodified version of the proposed method; paired percentages are not before/after measurements unless the evidence explicitly identifies such a design. First compare each variant against its OWN paired reference; separately compare reported variant rates only within the same dataset/metric and shared-reference scope. Name both sides of every directional claim. A rate below the full model does not mean a loss to the reference, and a win against the reference does not prove a head-to-head win against another variant.
For a broad ablation question with complete supplied rows, include a compact dataset-by-variant table for the primary metric, explain every supplied variant, and discuss the other metrics and their counterexamples. Never say full rankings or values are absent merely because derived arithmetic was capacity-limited.
For performance, results or ablation questions, include representative source-backed numbers and important exceptions in the MAIN answer, alongside method explanations.
Cite the source containing the actual values. Do not cite a generic paragraph for a table number. Do not invent references, values or missing cells.
Never mix datasets, metrics or table scopes. Rates against a common reference do not establish direct head-to-head wins between candidates; explain that distinction.
If typed structure or scope is incomplete/ambiguous, state what cannot be determined and keep original sources available for human review. Do not guess.
'''



def pack_large_tables(evidence,threshold=64,question=''):
    """Group complete pairs losslessly; source IDs/fact IDs remain in local registry."""
    from .table_comparisons import comparison_reports
    result=copy.deepcopy(evidence)
    for item in result:
        facts=item.get('table_facts',[])
        if len(facts)<=threshold or not reliable(facts):continue
        groups={}
        for fact in facts:
            key=(fact['metric'],tuple(fact['comparison_methods']))
            groups.setdefault(key,{}).setdefault(fact['dataset'],{})[fact['method']]=fact['value']
        encoded=[]
        for (metric,pair),datasets in sorted(groups.items(),key=lambda v:(v[0][0].casefold()!='overall',v[0])):
            rows=[[dataset,*[values[method] for method in pair]] for dataset,values in sorted(datasets.items())]
            encoded.append({'metric':metric,'comparison_methods':list(pair),'columns':['dataset',*pair],'rows':rows})
        # Values are still exact; only repeated keys and opaque provenance IDs
        # are removed from the wire. Native facts and trace IDs are unchanged.
        item.pop('table_facts');item['table_fact_groups']=encoded
        # The paired rows already preserve every value; do not duplicate the
        # entire table as Markdown in the same request.
        reports=[]
        for report in comparison_reports(facts):
            cross=report['cross_group_observations']
            if not cross:continue
            ordering=[]
            for row in cross['rankings']:
                tiers={}
                for value in row['rates']:tiers.setdefault(value['rank'],[]).append(value['method'])
                ordering.append([row['dataset'],[tiers[rank] for rank in sorted(tiers)]])
            reports.append({'metric':report['metric'],'common_reference':cross['common_reference'],
                'descending_rate_order_with_ties':ordering,
                'pairwise_rate_patterns':[p for p in cross['patterns']
                    if named(question,p['left']) or named(question,p['right'])]})
        item['computed_comparisons']={'scope':'Exact numeric ordering of reported rates against the named common reference; NOT direct head-to-head wins or before/after changes.',
            'reports':reports,'coverage':'All metrics and datasets in table_fact_groups; no derived metric was omitted.'}
    return result
