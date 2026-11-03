"""Present validated content by structure, without stripping Markdown strings."""
import copy
import re
from collections import OrderedDict
from .rag.core import SCHEMA as LEGACY_SCHEMA,validate_answer,GroundingError
from .rag.quality_contract import QualityContract


def table_requested(question):
    if re.search(r'\b(?:no|without)\s+(?:a\s+|any\s+)?tables?\b|不要.{0,3}表格|不需要.{0,3}表格',question,re.I):return False
    return bool(re.search(
        r'\b(?:show|provide|give|create|make|present|display|include|return|list)\s+'
        r'(?:me\s+)?(?:(?:a|an|the|all|full|complete|detailed|comparison|comparative|results?|numerical|summary)\s+)*tables?\b|'
        r'\b(?:in|as)\s+a\s+(?:comparison\s+)?table\b|\bin\s+table\s+(?:format|form)\b|\btabular\s+(?:form|format|data)\b|'
        r'\b(?:detailed|all|complete)\s+(?:numerical\s+)?(?:data|values|results|numbers)\b|'
        r'(?:提供|給我|呈現|顯示|列出|製作).{0,25}(?:比較表|表格)|(?:用|以).{0,8}(?:比較表|表格)|'
        r'詳細數據|詳細數值|完整數據|完整數值',question,re.I))


def numeric_requested(question):
    return bool(re.search(r'\b(?:how many|how much|percentages?|values?|scores?|rates?|costs?|tokens?|numbers?)\b|多少|數值|數據|百分比|成本',question,re.I))


def table_markdown(rows):
    def cell(value):return str(value).replace('|',r'\|').replace('\n',' ')
    lines=['| Method | Dataset | Metric | Comparison group | Value | Source |',
        '| --- | --- | --- | --- | --- | --- |']
    for row in rows:
        values=[row['method'],row['dataset'],row['metric'],' vs '.join(row['comparison_methods']),row['value']]
        lines.append('| '+' | '.join(cell(v) for v in values)+f" | [{row['evidence_id']}] (PDF pages {row['pages']}) |")
    return '\n'.join(lines)


def present_answer(validated,registry,question,document):
    # Rebuild from the normalized schema, including for old cached responses.
    # The complete original rendering still goes through every existing check.
    meta=validated['quality_contract']
    rendered=QualityContract._render(meta['payload'],registry,meta['mode'])
    checked=QualityContract().validate(rendered,registry)
    blocks=rendered['content_blocks'];main=[blocks['prose_markdown'].strip()]
    grouped=OrderedDict()
    seen=set()
    for row in blocks['table_rows']:
        if row['fact_id'] in seen:continue
        seen.add(row['fact_id']);grouped.setdefault(row['table_id'],[]).append(row)
    native={table['table_id']:table for table in document.get('tables',[])}
    table_citations={}
    for citation in rendered['citations']:
        key=citation['evidence_id'];source=registry[key]
        table_id=source.get('parent_table_id') or source.get('table_id')
        if table_id in native:
            grouped.setdefault(table_id,[])
            table_citations.setdefault(table_id,[]).append(key)
    tables=[]
    for table_id,rows in grouped.items():
        table=native.get(table_id,{})
        tables.append({'table_id':table_id,'table_number':rows[0]['table_number'] if rows else table.get('table_number'),
            'pages':sorted({page for row in rows for page in row['pages']}) if rows else table.get('page_numbers',[]),
            'evidence_ids':list(dict.fromkeys([row['evidence_id'] for row in rows]+table_citations.get(table_id,[]))),
            'rows':rows,'native_grid':copy.deepcopy(table.get('grid',[])),
            'scope':'Complete supplied facts; native grid is original parser output, not independently human-verified.'})
    detailed=table_requested(question)
    if detailed:
        main.extend(table_markdown(table['rows']) for table in tables if table['rows'])
    elif numeric_requested(question):
        for table in tables:
            for row in table['rows']:
                main.append(f"- {row['method']} — {row['dataset']} / {row['metric']} / {' vs '.join(row['comparison_methods'])}: {row['value']} [{row['evidence_id']}]")
    elif not main[0] and any(table['rows'] for table in tables):
        raise GroundingError('No substantive main answer generated; supporting tables cannot replace the requested explanation')
    observations=blocks['numeric_observations']
    if meta['mode']=='qa' and (numeric_requested(question) or not any(main)):
        # Use only the model-selected exact quote, never the renderer's appended
        # whole source paragraph. Full original text remains in sources.
        main.extend('> '+item['quote'].replace('\n','\n> ')+f" [{item['evidence_id']}]" for item in observations)
    if rendered['limitations']:
        main.append('### Limitations\n'+'\n'.join('- '+item for item in rendered['limitations']))
    answer=copy.deepcopy(rendered);answer.pop('content_blocks',None)
    answer['answer_markdown']='\n\n'.join(part for part in main if part)
    # Recheck citations, pages and every numerical tuple on the public primary
    # answer too. Detailed evidence has already passed the full contract above.
    validate_answer({key:answer[key] for key in LEGACY_SCHEMA['properties']},registry)
    quotes={key:[] for key in registry}
    for section in meta['payload']['sections']:
        for statement in section['statements']:
            for support in statement['support']:quotes[support['evidence_id']].append(support['quote'])
    for support in observations:quotes[support['evidence_id']].append(support['quote'])
    sources=[]
    for citation in rendered['citations']:
        key=citation['evidence_id'];source=registry[key]
        sources.append({'evidence_id':key,'pages':source['page_numbers'],'source_refs':source['source_refs'],
            'chunk_ids':source.get('origin_chunk_ids',[source.get('chunk_id')]),'text':source['text'],
            'quotes':list(dict.fromkeys(quotes[key])),'trust':source.get('trust','parser_output_pending_review')})
    return {'answer':answer,'sources':sources,'supporting_tables':tables,'validation':checked}


def present_assessed_answer(answer,registry,question,document,contract,extra_warnings=()):
    checks=contract.validate(answer,registry)
    if checks['status']=='failed':
        public=copy.deepcopy(answer);public.pop('failed_validation',None)
        sources=[{'evidence_id':key,'pages':source['page_numbers'],'source_refs':source.get('source_refs',[]),
            'text':source['text'],'quotes':[],'support_status':'review_required'} for key,source in registry.items()]
        tables=[{'table_id':table['table_id'],'table_number':table.get('table_number'),
            'pages':table.get('page_numbers',[]),'evidence_ids':[],'rows':[],
            'native_grid':copy.deepcopy(table.get('grid',[])),'scope':'Original parser output; not verified.'}
            for table in document.get('tables',[])]
        warnings=checks['warnings']+list(extra_warnings)
        return {'answer':public,'sources':[],'unverified_sources':sources,'supporting_tables':tables,
            'validation':{**checks,'warnings':warnings},'validation_status':'failed','validation_warnings':warnings}
    metadata=answer.get('assessment',{})
    validation_registry=registry
    if metadata.get('coverage_uncertain'):
        validation_registry=copy.deepcopy(registry)
        for source in validation_registry.values():source.pop('required_methods',None)
    result=present_answer(answer,validation_registry,question,document)
    warnings=list(checks['warnings'])+list(extra_warnings)
    if warnings:checks={**checks,'status':'review_required','warnings':warnings}
    unverified={key for warning in checks['warnings'] if not warning.get('stage') for key in warning['source_ids']}
    if checks['status'] in ('review_required','failed'):
        display=metadata['display_payload'];lines=[]
        for section in display['sections']:
            lines+=['### '+section['title'],'']
            for statement in section['statements']:
                ids=list(dict.fromkeys(item['evidence_id'] for item in statement['support']))
                refs=['['+key+(' · 待核對' if key in unverified else '')+']' for key in ids]
                lines.append(statement['text']+' '+(' '.join(refs) if refs else '（無可確認的引用）'))
            lines.append('')
        if table_requested(question):lines.extend(table_markdown(table['rows']) for table in result['supporting_tables'] if table['rows'])
        elif numeric_requested(question):
            for table in result['supporting_tables']:
                for row in table['rows']:
                    lines.append(f"- {row['method']} — {row['dataset']} / {row['metric']} / {' vs '.join(row['comparison_methods'])}: {row['value']} [{row['evidence_id']}]")
        if display['limitations']:lines+=['### Limitations',*display['limitations']]
        result['answer']['answer_markdown']='\n'.join(lines)
        result['answer']['evidence_status']='partial'
        result['answer']['unverified_citations']=[{'evidence_id':key,'pages':registry[key]['page_numbers']} for key in sorted(unverified)]
        result['answer']['citations']=[item for item in result['answer']['citations'] if item['evidence_id'] not in unverified]
        result['answer']['covered_source_ids']=[key for key in result['answer']['covered_source_ids'] if key not in unverified]
        result['answer']['numeric_claims']=[item for item in result['answer']['numeric_claims'] if item['evidence_id'] not in unverified]
    payload=metadata.get('display_payload',answer['quality_contract']['payload'])
    cited={support['evidence_id'] for section in payload['sections'] for statement in section['statements'] for support in statement['support']}
    if table_requested(question) or numeric_requested(question):
        cited.update(row['evidence_id'] for table in result['supporting_tables'] for row in table['rows'])
        cited.update(item['evidence_id'] for item in payload['numeric_observations'])
    raw_sources={source['evidence_id']:source for source in result['sources'] if source['evidence_id'] in cited}
    result['answer']['citations']=[item for item in result['answer']['citations'] if item['evidence_id'] in cited]
    result['answer']['covered_source_ids']=[key for key in result['answer']['covered_source_ids'] if key in cited]
    for key in unverified:
        if key not in raw_sources:
            source=registry[key]
            raw_sources[key]={'evidence_id':key,'pages':source['page_numbers'],'source_refs':source.get('source_refs',[]),
                'text':source['text'],'quotes':[],'trust':source.get('trust','parser_output_pending_review')}
    result['sources']=[{**source,'support_status':'confirmed','confirmation_scope':'source_id_and_exact_evidence_only'}
        for key,source in raw_sources.items() if key not in unverified]
    result['unverified_sources']=[{**raw_sources[key],'support_status':'review_required'} for key in sorted(unverified)]
    result['validation']=checks
    result['validation_status']=checks['status']
    result['validation_warnings']=warnings
    result['answer'].pop('assessment',None)
    return result
