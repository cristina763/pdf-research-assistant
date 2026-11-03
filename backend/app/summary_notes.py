"""Bounded summary transport; original quotes remain in the local registry."""
import copy
import re
from .rag.core import canonical

CATEGORIES=('background','method','experiments','conclusion')
NOTE_BYTES=6000

def bounded_note(note,limit=NOTE_BYTES,category_limits=None):
    result={'section':note.get('section',''),'supported_sections':[],'numeric_observations':[]}
    pools={category:[] for category in CATEGORIES}
    seen=set()
    for section in note.get('supported_sections',[]):
        category=section['category']
        if category not in pools:continue
        for statement in section['statements']:
            ids=list(dict.fromkeys(item.get('evidence_id',item.get('source_id')) for item in statement['support']))
            key=(statement['text'],tuple(ids))
            if (not ids and not note.get('manual_review')) or key in seen:continue
            seen.add(key)
            pools[category].append({'text':statement['text'],'support':[{'evidence_id':key} for key in ids],**({'source_topic':statement['source_topic']} if statement.get('source_topic') else {})})
    def purpose_score(item):
        text=item['text'].lower()
        return (item.get('source_topic')!='related_work',len(re.findall(r'flat|fragment|context|inter.depend|problem|limitation',text)),bool(re.search(r'aim|purpose|goal|objective|motivat|problem|limit|propos',text)),
            not bool(re.search(r'author|document is titled|reference list',text)))
    pools['background'].sort(key=purpose_score,reverse=True)
    if note.get('manual_review'):
        chosen=[]
        for pattern in (r'incremental|new data|union of|updat',r'low.level|high.level|local.*global',r'index|extract.*entit|profil|deduplic'):
            candidates=[item for item in pools['method'] if re.search(pattern,item['text'],re.I)]
            concrete=r'union|merg|node|edge' if 'incremental' in pattern else r'keyword|match|local|global|entit|relation' if 'low.level' in pattern else r'extract|profil|deduplic|key.value'
            item=max(candidates,key=lambda item:len(re.findall(concrete,item['text'],re.I))) if candidates else None
            if item is not None and item not in chosen:chosen.append(item)
        pools['method']=chosen+[item for item in pools['method'] if item not in chosen]
    experiments=pools['experiments']
    setup=next((item for item in experiments if item.get('source_topic')=='experimental_setup'),None) or next((item for item in experiments if re.search(r'evaluat|dataset|benchmark|experiment.*use',item['text'],re.I)),None)
    numerical=next((item for item in experiments if re.search(r'\d',item['text']) and re.search(r'result|score|rate|finding|outperform|improv|decline|exception',item['text'],re.I)),None)
    finding=next((item for item in experiments if item.get('source_topic')=='reported_results'),None) or numerical or next((item for item in experiments if re.search(r'result|finding|show|outperform|improv|trade.off|decline',item['text'],re.I)),None)
    preferred=[item for item in (setup,finding) if item is not None]
    if note.get('manual_review'):
        for pattern in (r'ablat|variant|remov',r'cost|token|api call|efficien|incremental'):
            topic='ablation' if pattern.startswith('ablat') else 'cost'
            extra=next((item for item in experiments if item.get('source_topic')==topic),None) or next((item for item in experiments if re.search(pattern,item['text'],re.I)),None)
            if extra is not None:preferred.append(extra)
    pools['experiments']=[*{canonical(item):item for item in preferred}.values(),*[item for item in experiments if item not in preferred]]
    # Reserve a slot for each purpose, method, evaluation/result and conclusion
    # before considering a second statement. Quotes are never duplicated here.
    for index in range(4 if note.get('manual_review') else 2):
        for category in ('experiments','conclusion','background','method'):
            if index>=len(pools[category]) or category_limits and index>=category_limits.get(category,4):continue
            candidate=copy.deepcopy(result)
            entry=next((s for s in candidate['supported_sections'] if s['category']==category),None)
            if entry is None:
                entry={'category':category,'title':category,'statements':[]};candidate['supported_sections'].append(entry)
            entry['statements'].append(pools[category][index])
            if len(canonical(candidate).encode('utf8'))<=limit:result=candidate
    if not result['supported_sections']:
        # For rejected notes only, bound original source DATA, not generated prose.
        prose=[]
        for source in note.get('original_prose',[]):
            item=copy.deepcopy(source)
            # Source chunks are bounded already; keep complete original excerpts.
            candidate={'section':result['section'],'original_prose':prose+[item]}
            if len(canonical(candidate).encode('utf8'))<=limit:prose.append(item)
            if len(prose)==2:break
        if prose:result={'section':result['section'],'original_prose':prose}
    if note.get('manual_review'):result['manual_review']=True
    return result


def transport_size(notes):return len(canonical([bounded_note(note) for note in notes]).encode('utf8'))


def bounded_children(note,children):
    result=copy.deepcopy(note)
    present={s['category'] for s in result.get('supported_sections',[]) if s['statements']}
    carried=[]
    for child in children:
        for entry in child.get('supported_sections',[]):
            if entry['category'] in CATEGORIES and entry['category'] not in present and entry['statements']:
                result.setdefault('supported_sections',[]).append(copy.deepcopy(entry))
                present.add(entry['category']);carried.append(entry['category'])
    compact=bounded_note(result)
    # Restore only selected exact original supports for LOCAL use/validation.
    selected={(s['text'],tuple(x['evidence_id'] for x in s['support'])) for e in compact.get('supported_sections',[]) for s in e['statements']}
    retained=[];included=set()
    for entry in result.get('supported_sections',[]):
        statements=[]
        for statement in entry['statements']:
            key=(statement['text'],tuple(dict.fromkeys(x['evidence_id'] for x in statement['support'])))
            if key in selected and key not in included:
                statements.append(statement);included.add(key)
        if statements:retained.append({**entry,'statements':statements[:4 if note.get('manual_review') else 2]})
    result['supported_sections']=retained
    if carried:result['coverage_carried_categories']=[c for c in carried if any(e['category']==c for e in retained)]
    result['numeric_observations']=[]
    return result


def anchor_sections_to_sources(sections,registry):
    """Route generated findings by cited original headings, without rewriting text.

    A model's label is not reliable provenance: an experimental-setup statement
    labelled 'method' must not crowd out the actual indexing/update mechanism.
    """
    groups={}
    for section in sections:
        for original in section.get('statements',[]):
            statement=copy.deepcopy(original)
            keys=[support.get('evidence_id',support.get('source_id')) for support in statement.get('support',[])]
            paths=' / '.join(' / '.join(registry.get(key,{}).get('section_path',[])) for key in keys)
            text=statement.get('text','')
            topic='overview';category=section.get('category','background')
            if re.search(r'experimental (?:settings|setup|design|data)|evaluation (?:setup|protocol)',paths,re.I):topic='experimental_setup';category='experiments'
            elif re.search(r'ablat',paths,re.I):topic='ablation';category='experiments'
            elif re.search(r'cost|adaptability|efficiency analysis',paths,re.I):topic='cost';category='experiments'
            elif re.search(r'evaluat|experiments|results|performance|case study',paths,re.I):topic='reported_results';category='experiments'
            elif re.search(r'indexing|architecture|method|approach|framework|retrieval paradigm|answer generation',paths,re.I) and re.search(r'\d|indexing|architecture|retrieval paradigm|answer generation',paths,re.I):
                topic='incremental' if re.search(r'incremental|union|merg|updat',text,re.I) else 'mechanism';category='method'
            elif re.search(r'conclusion',paths,re.I):topic='conclusion';category='conclusion'
            elif re.search(r'related work|references|bibliograph',paths,re.I):topic='related_work';category='background'
            statement['source_topic']=topic
            groups.setdefault(category,[]).append(statement)
    return [{'category':category,'title':category,'statements':statements} for category,statements in groups.items()]
