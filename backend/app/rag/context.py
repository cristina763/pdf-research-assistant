"""Evidence assembly only, with parent lookups and an injectable token counter."""



def bytes_count(text):return len(text.encode('utf-8'))


def fact_text(f):
    return (f"Table {f['table_number']} | Dataset={f['dataset']} | Comparison={' vs '.join(f['comparison_methods'])} | "
            f"Method={f['method']} | Metric={f['metric']} | Value={f['value']}")


class ContextAssembler:
    def __init__(self,chunks,document=None,counter=None,max_context=10000,system=1500,question=500,answer=2000):
        self.chunks={c['chunk_id']:c for c in chunks}
        self.document=document
        if document is None:raise ValueError('Explicit document is required')
        self.tables={t['table_id']:t for t in self.document['tables']}
        self.figures={f['figure_id']:f for f in self.document['figures']}
        self.facts={f['fact_id']:f for t in self.tables.values() for f in t['facts']}
        self.section_body=[e for e in self.document['elements'] if e['content_type']=='text' and e['text'].strip()]
        self.counter=counter or bytes_count;self.counter_name='provided_callback' if counter else 'UTF8_byte_proxy_not_final_LLM_tokens'
        self.budget=max_context-system-question-answer
        if self.budget<0:raise ValueError('Negative retrieval budget')
        # Fact integrity is based on the saved structure, never on a retrieval score.
        for f in self.facts.values():
            t=self.tables[f['table_id']];r=f['row_index'];c=f['column_index']
            assert f['value']==t['grid'][r][c]==f['source_cell']['text']
            assert f['method']==t['grid'][f['method_header_row']][c]
            assert f['dataset']==t['grid'][0][c]

    def assemble(self,hits):
        accepted=[];skipped=[];seen=set();seen_facts=set();seen_figures=set();seen_support=set();pieces=[]
        for hit in hits:
            key=hit['chunk_id']
            if key in seen:skipped.append({'chunk_id':key,'reason':'duplicate_chunk'});continue
            seen.add(key);c=self.chunks[key];fact_ids=[];sources=c['source_refs'];trust='parser_output_not_human_verified_in_full'
            if c.get('kind')=='figure':
                figure=self.figures[c['figure_id']]
                if c['figure_id'] in seen_figures:
                    skipped.append({'chunk_id':key,'reason':'duplicate_figure_caption'});continue
                text='Original caption only: '+figure['original_caption']['text']
                text+='\n[Image association pending human confirmation; candidate body descriptions omitted.]'
                sources=[figure['original_caption']['source_ref']];trust='caption_only_association_unverified'
            elif c.get('kind')=='table_facts':
                table=self.tables[c['table_id']]
                fact_ids=[fid for fid in c['fact_ids'] if fid not in seen_facts]
                if not fact_ids:skipped.append({'chunk_id':key,'reason':'duplicate_facts'});continue
                text='\n'.join(table['captions'])+'\n'+'\n'.join(fact_text(self.facts[fid]) for fid in fact_ids)
                trust='native_structure_validated; human_verification_pending'
            elif c.get('kind')=='table_cell':
                table=self.tables[c['table_id']]
                cols=set(range(*c['column_range']))
                headers=[cell['text'] for cell in table['native']['data']['table_cells'] if cell.get('column_header')
                         and cols.intersection(range(cell['start_col_offset_idx'],cell['end_col_offset_idx']))][:6]
                text='Parent table headers (parser, not independently verified): '+' / '.join(headers)+'\n'+c['text']
            else:text=c['text']
            pages=sorted({p['page_no'] for p in c['provenance'] if p['source_ref'] in sources})
            citation=f'[C{len(accepted)+1} | PDF pages {pages} | chunk {key} | document {c["document_id"]}]'
            piece=citation+'\n'+text
            candidate='\n\n'.join(pieces+[piece])
            if self.counter(candidate)>self.budget:
                skipped.append({'chunk_id':key,'reason':'retrieval_budget_exceeded'});continue
            pieces.append(piece);seen_facts.update(fact_ids)
            if c.get('kind')=='figure':seen_figures.add(c['figure_id'])
            accepted.append({'chunk_id':key,'text':piece,'fact_ids':fact_ids,'source_refs':sources,
                'page_numbers':pages,'section_path':c['section_path'],'trust':trust,
                'provenance':[p for p in c['provenance'] if p['source_ref'] in sources],
                'parent_table_id':c.get('table_id'),'parent_figure_id':c.get('figure_id')})
            # Query-independent parent enrichment: one complete same-section/page paragraph.
            # Ranking remains untouched. Expansion is separately tagged and budgeted.
            if c.get('kind')=='table_facts':
                table=self.tables[c['table_id']]
                candidates=[e for e in self.section_body if e['section_path']==table['section_path']
                            and set(e['page_numbers']).intersection(table['page_numbers'])]
                for body in candidates[:1]:
                    if body['source_ref'] in seen_support:continue
                    citation=f'[C{len(accepted)+1} | PDF pages {body["page_numbers"]} | parent-table section body {body["source_ref"]}]'
                    extra=citation+'\n'+body['text']
                    if self.counter(extra)>1600 or self.counter('\n\n'.join(pieces+[extra]))>self.budget:
                        skipped.append({'chunk_id':key,'reason':'parent_body_budget_exceeded','source_ref':body['source_ref']});continue
                    pieces.append(extra);seen_support.add(body['source_ref'])
                    accepted.append({'chunk_id':key+':parent-body:'+body['element_id'],'derived_from_chunk_id':key,
                        'text':extra,'fact_ids':[],'source_refs':[body['source_ref']],'page_numbers':body['page_numbers'],
                        'section_path':body['section_path'],'provenance':[{'source_ref':body['source_ref'],**p} for p in body['provenance']],
                        'trust':'parser_same_section_page_body; human_ground_truth_pending','parent_table_id':table['table_id']})
        context='\n\n'.join(pieces)
        return {'context':context,'evidence':accepted,'skipped':skipped,'count':self.counter(context),'budget':self.budget,
                'counter':self.counter_name,'final_LLM_10K_guaranteed':False,'answer_generated':False}
