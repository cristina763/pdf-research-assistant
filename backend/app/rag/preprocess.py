"""Deterministic structure-preserving projections and bounded retrieval chunks."""
import hashlib
import json
import re
from pathlib import Path

from decimal import Decimal

def numeric(value):
    value=value.strip()
    return Decimal(value[:-1]) if re.fullmatch(r'[+-]?\d+(?:\.\d+)?%',value) else None

MAX_BYTES=2048


def uid(*values):
    return hashlib.sha256('\0'.join(map(str,values)).encode('utf-8')).hexdigest()[:24]


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def jsonl(path,rows):
    path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')


def split_bytes(text,limit):
    """UTF-8-safe fixed byte windows, recording exact character offsets."""
    if limit<4: raise ValueError('Budget must allow a UTF-8 codepoint')
    start=0
    while start<len(text):
        end=start; size=0
        while end<len(text) and size+len(text[end].encode('utf-8'))<=limit:
            size+=len(text[end].encode('utf-8')); end+=1
        yield start,end,text[start:end]
        start=end


def split_preserving_words(text,limit):
    start=0
    while start<len(text):
        _,relative_end,_=next(split_bytes(text[start:],limit))
        end=start+relative_end
        if end<len(text) and text[end-1].isascii() and not text[end-1].isspace() and text[end].isascii() and not text[end].isspace():
            separators=[m.end() for m in re.finditer(r'\s+',text[start:end])]
            if not separators: raise ValueError('An indivisible ASCII token exceeds the context budget')
            end=start+separators[-1]
        yield start,end,text[start:end]
        start=end


def catalog(doc,document_id):
    elements=[]; headings={}
    for item,_ in doc.iterate_items():
        label=item.label.value
        if label in ('title','section_header'):
            level=getattr(item,'level',0)
            headings={k:v for k,v in headings.items() if k<level}
            headings[level]=getattr(item,'text','')
        prov=[p.model_dump(mode='json') for p in getattr(item,'prov',[])]
        text=getattr(item,'text','')
        elements.append({'element_id':uid(document_id,item.self_ref),'source_ref':item.self_ref,
            'document_id':document_id,'page_numbers':sorted({p['page_no'] for p in prov}),
            'section_path':[headings[k] for k in sorted(headings)],'content_type':label,'text':text,
            'original_extracted_text':getattr(item,'orig',''),'provenance':prov,
            'warnings':['formula_text_empty_not_repaired'] if label=='formula' and not text.strip() else []})
    return elements


def table_projection(table,doc,lookup,document_id):
    captions=[c.resolve(doc).text for c in table.captions]
    label=next((re.match(r'^Table\s+(\d+)\s*[:.]',c,re.I).group(1) for c in captions if re.match(r'^Table\s+(\d+)\s*[:.]',c,re.I)),None)
    grid=[[c.text for c in row] for row in table.data.grid]
    base=lookup[table.self_ref]
    result={'table_id':uid(document_id,table.self_ref),'source_ref':table.self_ref,
            'document_id':document_id,'table_number':int(label) if label else None,
            'page_numbers':base['page_numbers'],'section_path':base['section_path'],
            'captions':captions,'caption_refs':[c.cref for c in table.captions],'provenance':base['provenance'],
            'native':table.model_dump(mode='json'),'grid':grid,'facts':[],
            'scope':'Native cells preserved; typed facts only for unambiguous paired percentage headers.'}
    # Only project the verified paired-percentage structure; all other layouts
    # retain native cells without guessing semantic method/dataset relationships.
    headers=[i for i,row in enumerate(grid) if i and row and not row[0].strip()
             and any(c.strip() for c in row[1:]) and not any(numeric(c) is not None for c in row)]
    valid=bool(headers) and len(grid[0])>=3
    for ri,row in enumerate(grid):
        for ci,value in enumerate(row[1:],1):
            if numeric(value) is None:continue
            previous=[h for h in headers if h<ri]
            if not previous or not row[0].strip():valid=False;continue
            header=grid[previous[-1]];left=1+2*((ci-1)//2)
            if ci>=len(grid[0]) or not grid[0][ci].strip() or len(header[left:left+2])!=2 or not all(x.strip() for x in header[left:left+2]):valid=False
    if not valid:return result
    header=None
    for ri,row in enumerate(grid):
        if not row: continue
        if ri and not row[0].strip() and any(c.strip() for c in row[1:]) and not any(numeric(c) is not None for c in row):
            header=ri; continue
        if header is None or not row[0].strip(): continue
        for ci,value in enumerate(row[1:],1):
            if numeric(value) is None: continue
            left=1+2*((ci-1)//2)
            pair=grid[header][left:left+2]
            if len(pair)!=2: raise ValueError('Unexpected comparison pair')
            matching=[c for c in table.data.table_cells if c.start_row_offset_idx<=ri<c.end_row_offset_idx
                      and c.start_col_offset_idx<=ci<c.end_col_offset_idx]
            assert len(matching)==1,'Ambiguous source cell'
            result['facts'].append({'fact_id':uid(result['table_id'],ri,ci),'table_id':result['table_id'],
                'table_number':result['table_number'],'dataset':grid[0][ci], 'method':grid[header][ci],
                'comparison_methods':pair,'metric':row[0],'value':value,'numeric_unit':'percent',
                'row_index':ri,'column_index':ci,'method_header_row':header,
                'source_cell':matching[0].model_dump(mode='json'),
                'page_numbers':base['page_numbers'],'provenance':base['provenance']})
    return result


def fact_line(fact):
    return (f"Table {fact['table_number']} | Dataset={fact['dataset']} | "
            f"Comparison={' vs '.join(fact['comparison_methods'])} | Method={fact['method']} | "
            f"Metric={fact['metric']} | Value={fact['value']}")


def wrap(document_id,method,text,refs,lookup,headings=None,**extra):
    refs=sorted(set(refs))
    prov=[{'source_ref':r,**p} for r in refs for p in lookup[r]['provenance']]
    return {'chunk_id':uid(document_id,method,text,*refs),'document_id':document_id,'method':method,
            'text':text,'byte_tokens':len(text.encode('utf-8')),'section_path':headings or [],
            'source_refs':refs,'page_numbers':sorted({p['page_no'] for p in prov}),'provenance':prov,**extra}


def chunk_native(doc,chunker,method,lookup,document_id):
    rows=[]; raw=[]
    for c in chunker.chunk(dl_doc=doc):
        refs=[i.self_ref for i in c.meta.doc_items if i.self_ref in lookup]
        text=chunker.contextualize(chunk=c)
        rows.append(wrap(document_id,method,text,refs,lookup,c.meta.headings,
                         body_text=c.text,content_types=sorted({lookup[r]['content_type'] for r in refs})))
        raw.append(c)
    return rows,raw


def atomic_chunks(prefix,lines):
    """Repeat context; preserve each typed fact line as an indivisible unit."""
    batch=[]
    for key,line in lines:
        if len((prefix+'\n'+line).encode('utf-8'))>MAX_BYTES:
            raise ValueError('An atomic fact and its context exceed the byte budget')
        if batch and len((prefix+'\n'+'\n'.join(x[1] for x in batch)+ '\n'+line).encode('utf-8'))>MAX_BYTES:
            yield batch,prefix+'\n'+'\n'.join(x[1] for x in batch)
            batch=[]
        batch.append((key,line))
    if batch: yield batch,prefix+'\n'+'\n'.join(x[1] for x in batch)


def bounded_chunks(hierarchical,tables,figures,lookup,document_id):
    result=[]
    target_tables={t['source_ref'] for t in tables}
    figure_refs={r for figure in figures for r in [figure['picture_ref'],*figure['caption_refs']]}
    for c in hierarchical:
        refs=c['source_refs']
        if any(r in target_tables for r in refs):
            # A table chunk can include its caption, both retained in the table projection.
            assert all(r in target_tables or lookup[r]['content_type']=='caption' for r in refs)
            continue
        if refs and all(r in figure_refs for r in refs): continue
        prefix='Section: '+' / '.join(c['section_path'])+'\n'
        capacity=MAX_BYTES-len(prefix.encode('utf-8'))
        if capacity<64: raise ValueError('Heading metadata exceeds narrative budget')
        for start,end,body in split_preserving_words(c['body_text'],capacity):
            if not body.strip(): continue
            result.append(wrap(document_id,'structure_bounded',prefix+body,refs,lookup,c['section_path'],
                               parent_chunk_id=c['chunk_id'],parent_char_start=start,parent_char_end=end,
                               content_types=c['content_types'],kind='narrative',
                               table_refs=[r for r in refs if lookup[r]['content_type']=='table']))
    for table in tables:
        prefix='Section: '+' / '.join(table['section_path'])+'\n'+'\n'.join(table['captions'])
        refs=[table['source_ref'],*table['caption_refs']]
        if not table['facts']:
            for index,cell in enumerate(table['native']['data']['table_cells']):
                text=cell['text']
                if not text.strip(): continue
                row_range=[cell['start_row_offset_idx'],cell['end_row_offset_idx']]
                col_range=[cell['start_col_offset_idx'],cell['end_col_offset_idx']]
                context=prefix+f'\nNative table {table["source_ref"]} | Cell {index} | rows={row_range} | columns={col_range}\n'
                capacity=MAX_BYTES-len(context.encode('utf-8'))
                for start,end,body in split_preserving_words(text,capacity):
                    if not body.strip(): continue
                    result.append(wrap(document_id,'structure_bounded',context+body,refs,lookup,table['section_path'],
                        kind='table_cell',content_types=['table'],table_id=table['table_id'],native_table_ref=table['source_ref'],
                        source_cell_index=index,row_range=row_range,column_range=col_range,
                        cell_char_start=start,cell_char_end=end,
                        relationship_status='cell_coordinates_preserved; semantic_header_interpretation_pending'))
            continue
        lines=[(f['fact_id'],fact_line(f)) for f in table['facts']]
        for batch,text in atomic_chunks(prefix,lines):
            result.append(wrap(document_id,'structure_bounded',text,refs,lookup,table['section_path'],
                               kind='table_facts',content_types=['table'],table_id=table['table_id'],
                               fact_ids=[key for key,line in batch],text_origin='deterministic_field_serialization_not_new_data'))
    for figure in figures:
        caption=figure['original_caption']; refs=[figure['picture_ref'],*figure['caption_refs']]
        prefix='Section: '+' / '.join(figure['section_path'])+'\nOriginal caption: '
        capacity=MAX_BYTES-len(prefix.encode('utf-8'))
        for start,end,body in split_preserving_words(caption['text'],capacity):
            if body.strip():result.append(wrap(document_id,'structure_bounded',prefix+body,refs,lookup,figure['section_path'],
                kind='figure',content_types=['picture','caption'],figure_id=figure['figure_id']))
    return result


def build(doc,document_id):
    from docling.chunking import HierarchicalChunker
    elements=catalog(doc,document_id);lookup={e['source_ref']:e for e in elements}
    tables=[table_projection(t,doc,lookup,document_id) for t in doc.tables]
    figures=[]
    for picture in doc.pictures:
        refs=[r.cref for r in picture.captions if r.cref in lookup]
        if not refs:continue  # Never infer an image-caption relationship.
        caption=lookup[refs[0]]
        figures.append({'figure_id':uid(document_id,picture.self_ref),'picture_ref':picture.self_ref,
            'caption_refs':refs,'page_numbers':lookup[picture.self_ref]['page_numbers'],
            'section_path':caption['section_path'],'original_caption':{'text':'\n'.join(lookup[r]['text'] for r in refs),
            'source_ref':refs[0]},'association_status':'native_caption_reference','system_generated_description':None})
    hierarchical,_=chunk_native(doc,HierarchicalChunker(),'hierarchical_native',lookup,document_id)
    chunks=bounded_chunks(hierarchical,tables,figures,lookup,document_id)
    chunks=[c for c in chunks if c['page_numbers'] and c['text'].strip()]
    if not chunks:raise ValueError('PDF has no searchable text; scanned PDFs need OCR, which is disabled.')
    if any(c['byte_tokens']>MAX_BYTES for c in chunks):raise ValueError('Chunk exceeds 2048-byte policy')
    document={'schema_version':'1.0','document_id':document_id,'elements':elements,'tables':tables,'figures':figures,
        'source':{'page_count':len(doc.pages),'parser':'Docling Fast'},'chunk_max_bytes':MAX_BYTES}
    return document,chunks
