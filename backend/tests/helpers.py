"""Synthetic parser/provider for basic tests only, never imported by the website."""
import json
class SyntheticParser:
    def __init__(self):self.calls=0
    def parse(self,path,docid):
        self.calls+=1;text='Synthetic document explains retrieval methods, evidence and reliable source citations.'
        if b'other' in path.read_bytes():text+=' Distinct zeppelin.'
        else:text+=' Distinct telescope.'
        p={'page_no':1,'bbox':{},'charspan':[0,len(text)]}
        e={'element_id':'sample','source_ref':'#/texts/0','document_id':docid,'page_numbers':[1],'section_path':['Method'],'content_type':'text','text':text,'provenance':[p],'warnings':[]}
        c={'chunk_id':docid[:24],'document_id':docid,'kind':'narrative','text':text,'source_refs':['#/texts/0'],'page_numbers':[1],'section_path':['Method'],'provenance':[{'source_ref':'#/texts/0',**p}]}
        return {'document_id':docid,'elements':[e],'tables':[],'figures':[],'source':{'page_count':1}},[c],{}

class MockText:
    def __init__(self,count=100):self.count=count;self.calls=0;self.requests=[]
    def count_input(self,request):return self.count
    def generate(self,request):
        self.calls+=1;self.requests.append(request)
        props=request['text']['format']['schema']['properties'];sections=[]
        if props['sections'].get('maxItems')!=0:
            support=props['sections']['items']['properties']['statements']['items']['properties']['support']['items']['properties']['source_id']
            key=support.get('enum',['C1'])[0]
            categories=props['sections']['items']['properties']['category'].get('enum',['background'])
            sections=[{'category':cat,'title':cat,'statements':[{'text':'Mock flow test: current document evidence is available.','support':[{'source_id':key}]}]} for cat in categories[:4]]
        payload={'sections':sections,'table_views':[],'numeric_observations':[],'limitations':[],'evidence_status':'partial'}
        if 'source_quotes' in props:
            enum=props['source_quotes']['items']['properties']['source_id'].get('enum',[])
            payload['source_quotes']=[{'source_id':key} for key in enum[:props['source_quotes'].get('maxItems',0)]]
        if 'numeric_presentation' in props:
            fields=props['numeric_presentation']['properties'];payload['numeric_presentation']={name:value['enum'][0] for name,value in fields.items()}
        return {'status':'completed','id':'mock-'+str(self.calls),'model':'mock-text-flow','output':[{'content':[{'type':'output_text','text':json.dumps(payload)}]}], 'usage':{'input_tokens':self.count,'output_tokens':100,'total_tokens':self.count+100}}
    def ledger(self):return {'generation_requests':self.calls,'mock':True}
