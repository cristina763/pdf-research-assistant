"""Use existing retrieval/structured artifacts; never open a PDF."""
import re
from collections import OrderedDict

from .comparison import ComparisonAssembler
from .retrieval import BM25

class Corpus:
    def __init__(self,document,chunks,cache):
        self.chunks=chunks;self.bm25=BM25(chunks,cache=cache)
        self.assembler=ComparisonAssembler(chunks,document=document)
        self.document=document

    def qa(self,question,k=5):
        hits=self.bm25.query(question,k)
        context=self.assembler.assemble(hits,query=question)
        evidence=[];registry={}
        for i,entry in enumerate(context['evidence'],1):
            key=entry.get('evidence_id',f'C{i}')
            source={**entry,'evidence_id':key,'facts':[self.assembler.facts[f] for f in entry.get('fact_ids',[])]}
            evidence.append(self.compact(source));registry[key]=source
        return {'question':question,'hits':hits,'enhanced_context':context,'evidence':evidence,'registry':registry}

    @staticmethod
    def compact(source):
        result={'evidence_id':source['evidence_id'],'pages':source['page_numbers'],
                'section':source.get('section_path',[]),'trust':source.get('trust','parser_output_pending_manual_review'),
                'text':source['text']}
        if source.get('facts'):
            result['table_facts']=[{k:f[k] for k in ('method','dataset','metric','comparison_methods','value')}
                                   for f in source['facts']]
        return result

    def summary_sources(self):
        sources=[]
        for i,chunk in enumerate(self.chunks,1):
            source={**chunk,'evidence_id':f'S{i}','facts':[self.assembler.facts[f] for f in chunk.get('fact_ids',[])],
                    'trust':'parser_output_pending_manual_review'}
            if chunk['kind']=='figure':
                fig=self.assembler.figures[chunk['figure_id']]
                source['text']='Original caption: '+fig['original_caption']['text']+'\nImage association pending; candidate body explanations excluded.'
                source['facts']=[];source['trust']='caption_only_image_association_pending'
            sources.append(source)
        for element in self.document['elements']:
            if not element.get('warnings'):continue
            sources.append({'evidence_id':f'S{len(sources)+1}','chunk_id':None,
                'source_refs':[element['source_ref']],'page_numbers':element['page_numbers'],
                'section_path':element['section_path'],'facts':[],'provenance':element['provenance'],
                'text':'Parsing limitation: source formula text is empty and has not been repaired. Do not infer the formula.',
                'trust':'mechanical_parsing_limitation_notice_not_original_prose'})
        return sources


def section_key(source):
    for h in source.get('section_path',[]):
        m=re.match(r'^(\d+)(?:\.|\s)',h)
        if m:return 'Section '+m[1]
    if source.get('section_path'):return ' / '.join(source['section_path'])
    return 'References' if any('REFERENCES' in h for h in source.get('section_path',[])) else 'Front matter'
