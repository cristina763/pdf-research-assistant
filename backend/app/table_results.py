"""Source-table projections, not generated answers or an entailment judge.

Scope: complete paired numeric groups from the existing percentage-table parser.
Ordering means literal value order, never statistical significance or causality.
"""
import copy
import json
import re
from collections import defaultdict
from .numeric_context import reliable, named
from .table_comparisons import comparison_reports
from .rag.core import GroundingError


class NumericPresentationError(GroundingError):
    """Do not turn a rejected numeric presentation into an unchecked recovery."""


def table_records(registry, question='', summary=False):
    tables=defaultdict(dict)
    for source_id,source in registry.items():
        for fact in source.get('facts',[]):
            if not all(k in fact for k in ('table_id','dataset','metric','method','comparison_methods','value')):continue
            key=(fact['dataset'],fact['metric'],tuple(sorted(fact['comparison_methods'])),fact['method'])
            prior=tables[fact['table_id']].get(key)
            if prior and prior[1]['value']!=fact['value']:
                raise NumericPresentationError('Conflicting original table cells')
            tables[fact['table_id']].setdefault(key,(source_id,copy.deepcopy(fact)))
    result={}
    for table,records in sorted(tables.items()):
        pairs=list(records.values());facts=[f for _,f in pairs]
        if not reliable(facts):continue
        if not summary:
            metrics={f['metric'] for f in facts};datasets={f['dataset'] for f in facts};methods={f['method'] for f in facts}
            ms={m for m in metrics if named(question,m)};ds={d for d in datasets if named(question,d)};targets={m for m in methods if named(question,m)}
            pairs=[(k,f) for k,f in pairs if (not ms or f['metric'] in ms) and (not ds or f['dataset'] in ds)]
            # Named direct comparisons retain both sides, never one candidate's
            # rate against an unrelated reference. Broad variant queries retain all.
            explicit=re.search(r'\btable\s+(\d+)\b',question,re.I)
            if explicit:pairs=[(k,f) for k,f in pairs if f.get('table_number')==int(explicit.group(1))]
            if len(targets)>=2 and not re.search(r'ablat|variant|rank|highest|lowest',question,re.I):
                direct=[(k,f) for k,f in pairs if targets.issubset(f['comparison_methods'])]
                if direct:pairs=direct
        if pairs:result[table]=pairs
    return result


def cell(value):return str(value).replace('|',r'\|').replace('\n',' ')


def render_tables(registry,question,summary=False):
    lines=[];used=[];claims=[]
    def cite(key,fact):
        used.append(key)
        claim={'kind':'table_fact','evidence_id':key,**{k:copy.deepcopy(fact[k]) for k in ('method','dataset','metric','comparison_methods','value')},'quote':''}
        if claim not in claims:claims.append(claim)
        return '['+key+']'
    for table,pairs in table_records(registry,question,summary).items():
        facts=[f for _,f in pairs];lookup={(f['dataset'],f['metric'],tuple(sorted(f['comparison_methods'])),f['method']):(k,f) for k,f in pairs}
        reports=comparison_reports(facts)
        number=facts[0].get('table_number')
        label='Table '+str(number) if number is not None else 'Source table'
        lines+=['### '+label+': source values and computed ordering','',
            'Values retain their dataset, metric and comparison group. Percentages are not converted to accuracy. Ordering below is arithmetic, not a significance test.','']
        for index,report in enumerate(reports):
            primary=index==0
            # A summary shows one complete primary metric and mixed-direction
            # exceptions from the other metrics, rather than unrelated sample cells.
            if summary and not primary:
                for pattern in report['direct_patterns']:
                    for dataset in pattern['exceptions_to_majority']:
                        row=next(row for row in report['direct_pairs'] if row[0]==dataset and row[1]==pattern['left'] and row[4]==pattern['right'])
                        d,a,av,rel,b,bv=row
                        refs=[]
                        for method in (a,b):
                            k,f=lookup[(d,report['metric'],tuple(sorted((a,b))),method)];refs.append(cite(k,f))
                        lines.append('- Exception to the majority direction, '+cell(report['metric'])+', '+cell(d)+': `'+cell(a)+'` '+av+' '+rel+' `'+cell(b)+'` '+bv+'. '+' '.join(dict.fromkeys(refs)))
                continue
            cross=report['cross_group_observations']
            # Use a shared-reference grid only for multi-group data. Every
            # candidate keeps its OWN reference cell; no collapsed baseline column.
            if cross:
                ref=cross['common_reference'];candidates=sorted({f['method'] for f in facts if f['metric']==report['metric'] and f['method']!=ref})
                headers=['Dataset']
                for method in candidates:headers.extend([method,ref+' (paired with '+method+')'])
                lines+=['**'+cell(report['metric'])+'** - paired reference: `'+cell(ref)+'`. Candidate rates against this reference are not direct candidate-vs-candidate experiments.','',
                    '| '+' | '.join(cell(x) for x in headers)+' |','| '+' | '.join(['---']*len(headers))+' |']
                for rank in cross['rankings']:
                    dataset=rank['dataset'];row=[cell(dataset)];refs=[]
                    for method in candidates:
                        for name in (method,ref):
                            record=lookup.get((dataset,report['metric'],tuple(sorted((method,ref))),name))
                            if record:
                                k,f=record;row.append(cell(f['value']));refs.append(cite(k,f))
                            else:row.append('not supplied')
                    row[0]+=' '+' '.join(dict.fromkeys(refs));lines.append('| '+' | '.join(row)+' |')
                lines.append('')
                for rank in cross['rankings']:
                    tiers=defaultdict(list)
                    for rate in rank['rates']:tiers[rate['rank']].append('`'+cell(rate['method'])+'` ('+rate['value']+')')
                    refs=[]
                    for rate in rank['rates']:
                        k,f=lookup[(rank['dataset'],report['metric'],tuple(sorted((rate['method'],ref))),rate['method'])];refs.append(cite(k,f))
                    lines.append('- '+cell(rank['dataset'])+': '+' > '.join(' = '.join(tiers[t]) for t in sorted(tiers))+'. '+' '.join(dict.fromkeys(refs)))
            else:
                lines+=['**'+cell(report['metric'])+'**','',
                    '| Dataset | Method | Value | Numeric relation | Method | Value | Source |',
                    '| --- | --- | --- | --- | --- | --- | --- |']
                for dataset,a,av,rel,b,bv in report['direct_pairs']:
                    refs=[]
                    for method in (a,b):
                        k,f=lookup[(dataset,report['metric'],tuple(sorted((a,b))),method)];refs.append(cite(k,f))
                    lines.append('| '+' | '.join([cell(dataset),'`'+cell(a)+'`',av,rel,'`'+cell(b)+'`',bv,' '.join(dict.fromkeys(refs))])+' |')
                # The complete table, including minority reversals and ties, is
                # presented. Do not ask an LLM to infer a universal winner.
            lines.append('')
    return '\n'.join(lines),list(dict.fromkeys(used)),claims


def normalize_numeric(raw,registry,normalize):
    meta=raw['numeric_presentation'];summary=meta['mode']=='summary'
    if meta['mode'] not in ('qa','summary'):raise NumericPresentationError('Unknown numeric presentation mode')
    if not summary:return normalize_qa(raw,registry,normalize)
    from .summary_style import detailed_summary
    concise=summary and not detailed_summary(meta['question'])
    clean=copy.deepcopy(raw);clean.pop('numeric_presentation');quotes=clean.pop('source_quotes',[])
    clean['table_views']=[]
    policy=prose_policy(registry)
    empirical=set(policy['verbatim_source_ids']);routed=[];retained=[]
    for section in clean.get('sections',[]):
        statements=[]
        for statement in section.get('statements',[]):
            keys=[s['source_id'] for s in statement['support']]
            if not keys or any(k not in registry for k in keys):
                raise NumericPresentationError('Explanation has no supplied source')
            # Preserve the source choice, not an unchecked empirical/numeric
            # paraphrase. This is an extractive presentation fallback, never an
            # alternate generated answer or a paid repair/retry.
            extractive=(not summary and bool(set(keys)&empirical)) or any(registry[k].get('facts') for k in keys) or bool(re.search(r'\d|%',statement['text']))
            if extractive:
                routed.extend({'source_id':k} for k in keys if not registry[k].get('facts'))
            else:statements.append(statement)
        if statements:retained.append({**section,'statements':statements})
    clean['sections']=retained
    if clean.get('limitations'):
        raise NumericPresentationError('Presentation limitations come from source/processing metadata, not generated absence claims')
    quotes=routed+quotes
    quoted=[];seen=set()
    for item in quotes:
        key=item['source_id']
        if key not in registry or registry[key].get('facts'):
            raise NumericPresentationError('Interpretation must reference original prose')
        # The model selects an original passage ID. It never has to copy, repair
        # or reinterpret that passage. Historical explicit quotes remain checked.
        quote=item.get('quote',original_prose(registry[key]))
        if len(quote.strip())<20 or quote not in registry[key]['text'] or quote.startswith('Section:'):
            raise NumericPresentationError('Interpretation quote is not an exact original prose excerpt')
        if key not in seen:
            quoted.append({'text':'> '+quote.replace('\n','\n> '),'support':[{'source_id':key}]});seen.add(key)
    if concise and not retained:
        # A failed prose generation must remain visibly extractive, rather
        # than silently becoming a complete-looking, content-free summary.
        if not quoted:raise NumericPresentationError('No substantive summary prose or original-prose fallback')
        clean['sections']=[{'category':'experiments','title':'Original evidence fallback (summary prose unavailable)',
            'statements':quoted}]
    if quoted and not concise:clean.setdefault('sections',[]).append({'category':'experiments',
        'title':'Source explanations (verbatim; numerical exceptions are shown below)','statements':quoted})
    if not clean.get('sections'):
        keys=[key for pairs in table_records(registry,meta['question'],summary).values() for key,_ in pairs]
        clean['sections']=[{'category':'experiments','title':'Source-derived numerical evidence','statements':[{'text':'The original table values and their arithmetic relations are shown below.','support':[{'source_id':key} for key in dict.fromkeys(keys)]}]}]
    answer,repairs=normalize(clean,registry)
    text,ids,claims=render_tables(registry,meta['question'],summary)
    if not text:raise NumericPresentationError('No complete unambiguous numeric table remains')
    if not concise:answer['answer_markdown']+='\n\n'+text
    # Keep the complete validated projection in memory for source inspection;
    # it must not inflate a default summary or be written to disk.
    if concise:answer['supporting_numeric_markdown']=text
    for item in quoted:
        for support in item['support']:
            key=support['source_id']
            if key not in answer['covered_source_ids']:
                answer['covered_source_ids'].append(key)
                answer['citations'].append({'evidence_id':key,'pages':registry[key]['page_numbers']})
    for key in ids:
        if key not in answer['covered_source_ids']:
            answer['covered_source_ids'].append(key);answer['citations'].append({'evidence_id':key,'pages':registry[key]['page_numbers']})
    answer['numeric_claims']=claims;answer['manual_payload']=copy.deepcopy(raw)
    return answer,repairs


def normalize_qa(raw,registry,normalize):
    """Keep generated QA prose intact; never substitute extracted evidence."""
    from .failed_answer import readable_output
    clean=copy.deepcopy(raw)
    meta=clean.pop('numeric_presentation');quotes=clean.pop('source_quotes',[])
    answer_warnings=[]
    auxiliary_warnings=[]
    if not isinstance(quotes,list):
        quotes=[]
        auxiliary_warnings.append({'code':'invalid_supporting_reference',
            'message':'Auxiliary source selections were malformed; generated answer retained.','source_ids':[]})
    sections=clean.get('sections',[])
    if not sections:raise NumericPresentationError('Answer generation failed: no answer prose; supporting evidence is not an answer')
    has_answer_prose=False
    for section in sections:
        statements=section.get('statements',[])
        for statement in statements:
            text=statement.get('text','').strip()
            keys=[item.get('source_id') for item in statement.get('support',[])]
            for marker in re.findall(r'\[([CS][^]\n]*)\]',text):
                if marker not in registry:
                    answer_warnings.append({'code':'unmapped_citation',
                        'message':'A generated citation could not be mapped; answer text retained for review.',
                        'source_ids':[marker]})
            # Inspect a copy: legitimate citation markers must not cause a
            # numerical rejection or remove any part of the generated answer.
            numeric_text=re.sub(r'\[(?:[CS]\s*\d+\s*(?:[,;、]\s*)?)+\]','',text)
            # Structural rejection only, not a semantic correctness score.
            # A brief answer or a genuine insufficiency explanation is allowed.
            prose='\n'.join(line for line in text.splitlines()
                if not re.match(r'^\s*(?:[>|#]|```)',line)
                and not re.fullmatch(r'\s*(?:[-*]\s+)?[\w `-]+(?:\s+[><=]\s+[\w `-]+)+[.!]?\s*',line))
            prose=re.sub(r'\[[CS][^]\n]*\]','',prose)
            original_only=any(text==original_prose(registry[key]) for key in keys if key in registry)
            if re.search(r'[^\W\d_]',prose,re.UNICODE) and not original_only:has_answer_prose=True
            if re.search(r'\d|%',numeric_text):
                raise NumericPresentationError('Generated numerical prose rejected; exact values belong to supporting evidence')
    if any(re.search(r'\d|%',item) for item in clean.get('limitations',[])):
        raise NumericPresentationError('Generated numerical limitation rejected')
    if not has_answer_prose:
        raise NumericPresentationError('Answer generation failed: only citations, quotations or tables; no substantive generated prose')
    clean['table_views']=[];clean['numeric_observations']=[]
    answer,repairs=normalize(clean,registry)
    answer['citation_warnings'].extend(answer_warnings)
    # Render ONLY generated prose and its citations. Auxiliary evidence below
    # cannot replace, shorten or supply this answer, even when it fails.
    parts=[];original_statements=[]
    mapped_ids={item['evidence_id'] for item in answer['citations']}
    for section in clean['sections']:
        if section.get('title'):parts.append('### '+section['title'])
        for statement in section['statements']:
            text=statement['text'];original_statements.append(text)
            if readable_output(json.dumps({'answer_markdown':text})).strip()!=text.strip():
                raise NumericPresentationError('Generated answer contains protected credential-like content')
            refs=list(dict.fromkeys(item['source_id'] for item in statement.get('support',[])))
            missing=[key for key in refs if key in mapped_ids and '['+key+']' not in text]
            parts.append(text+(' '+' '.join('['+key+']' for key in missing) if missing else ''))
    parts.extend(clean.get('limitations',[]))
    answer['answer_markdown']='\n\n'.join(parts)
    answer['answer_integrity']={'model_statement_count':len(original_statements),
        'preserved_statement_count':sum(text in answer['answer_markdown'] for text in original_statements)}
    if answer['answer_integrity']['preserved_statement_count']!=len(original_statements):
        raise NumericPresentationError('Generated answer preservation check failed')
    from .rag.comparison_validation import check_comparison_directions
    comparison_sections=copy.deepcopy(clean['sections'])
    for section in comparison_sections:
        for statement in section['statements']:statement['text']=re.sub(r'\[[CS]\d+\]','',statement['text']).strip()
    check_comparison_directions(comparison_sections,registry)
    warnings=auxiliary_warnings
    try:text,ids,claims=render_tables(registry,meta['question'],False)
    except Exception:
        # Invalid derived evidence is withheld; the separately valid Answer is
        # still returned. Do not turn a supporting-table failure into lost prose.
        text='';ids=[];claims=[]
        warnings.append({'code':'supporting_numeric_unavailable',
            'message':'Supporting numeric evidence failed validation and was withheld; generated answer retained.',
            'source_ids':[]})
    for item in quotes:
        key=item.get('source_id') if isinstance(item,dict) else None
        if key not in registry or registry[key].get('facts'):
            warnings.append({'code':'invalid_supporting_reference',
                'message':'An auxiliary source selection could not be mapped; generated answer retained.',
                'source_ids':[key] if isinstance(key,str) else []})
            continue
        ids.append(key)
    ids=list(dict.fromkeys(ids))
    answer['answer_status']='insufficient_evidence' if clean.get('evidence_status')=='insufficient' else 'answered'
    answer['supporting_evidence']={'numeric_markdown':text,'numeric_claims':claims,
        'citations':[{'evidence_id':key,'pages':registry[key]['page_numbers']} for key in ids],
        'status':'partial' if warnings else 'available','warnings':warnings}
    answer['citation_warnings'].extend(warnings)
    answer['manual_payload']=copy.deepcopy(raw)
    return answer,repairs


def summary_anchors(registry,max_bytes=4500):
    """Small original-prose sidecar to prevent a compressed note being quoted.

    Research-format heuristic: literal minus-prefixed condition names and short
    paragraph lead-ins in method/architecture/retrieval sections. No paper IDs.
    Whole excerpts only; this is not a second retrieval engine.
    """
    variants={f['method'] for source in registry.values() for f in source.get('facts',[]) if f['method'].startswith('-')}
    candidates=[]
    for key,source in registry.items():
        if source.get('facts') or source.get('trust','').startswith('mechanical'):continue
        path=' / '.join(source.get('section_path',[]))
        if re.search(r'appendi|references|bibliograph|prompt templates',path,re.I):continue
        text=source.get('text','');body=text.split('\n',1)[-1] if text.startswith('Section:') else text
        variant=any(named(body,v) for v in variants)
        method=bool(re.search(r'method|architect|indexing|retrieval paradigm|approach',path,re.I))
        lead=bool(re.match(r'(?:[-*]\s+)?[A-Za-z][A-Za-z -]{2,65}[.:] ',body))
        if variant or method and lead:candidates.append((0 if variant else 1,key,source))
    output=[];size=0
    variant_candidates=[v for v in candidates if v[0]==0]
    by_section=defaultdict(list)
    for candidate in candidates:
        if candidate[0]:by_section[tuple(candidate[2].get('section_path',[]))].append(candidate)
    balanced=[]
    for index in range(max((len(v) for v in by_section.values()),default=0)):
        for values in by_section.values():
            if index<len(values):balanced.append(values[index])
    for _,key,source in variant_candidates+balanced:
        text=source['text'];cost=len(text.encode('utf8'))
        if size+cost>max_bytes:continue
        output.append({'evidence_id':key,'source_type':'pdf_excerpt','role':'original_summary_anchor',
            'section':source.get('section_path',[]),'text':text});size+=cost
    return output


def original_prose(source):
    text=source.get('text','')
    lines=text.splitlines()
    if lines and re.fullmatch(r'\[(?:C|S)\d+ \| PDF pages \[.*\] \| chunks .*\]',lines[0]):lines.pop(0)
    if lines and lines[0].startswith('Section: '):lines.pop(0)
    return '\n'.join(lines).strip()


def prose_policy(registry):
    """Research-format safeguard, not a universal document classifier.

    Empirical interpretations and condition definitions are displayed verbatim;
    explanatory prose remains generated. The policy uses source provenance,
    never a question ID, paper name, expected value or preferred answer.
    """
    paraphrase=[];verbatim=[]
    for key,source in registry.items():
        if source.get('facts') or source.get('trust','').startswith('mechanical'):continue
        body=original_prose(source);path=' / '.join(source.get('section_path',source.get('section',[])))
        if len(body)<20:continue
        if re.search(r'ablat|results?|performance|comparison|cost|adaptability|efficiency analysis|case study|conclusion',path,re.I):verbatim.append(key)
        elif len(body)>=80 and not re.search(r'appendi|references|bibliograph|prompt templates',path,re.I):paraphrase.append(key)
    return {'source_type':'presentation_policy','paraphrase_source_ids':paraphrase,'verbatim_source_ids':verbatim}
