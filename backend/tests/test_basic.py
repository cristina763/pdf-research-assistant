"""Basic offline checks; no benchmark answer key or archived response is needed."""
import hashlib,io,json,os
from pathlib import Path
import httpx,pytest
from fastapi.testclient import TestClient
from app.config import Settings,ROOT
from app.main import create_app
from app.parser import PDFParser
from app.store import DocumentStore
from app.rag.core import ContextLimitError,enforce_budget,make_request
from app.rag.provider import OpenAIText
from helpers import SyntheticParser,MockText
from runtime_env import load_local_env

def upload(client,content=b'%PDF-synthetic'):
    return client.post('/documents',files={'file':('sample.pdf',content,'application/pdf')})
def state(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def setup(tmp_path,provider=None):
    parser=SyntheticParser();provider=provider or MockText()
    app=create_app(Settings(data_dir=tmp_path,generation_enabled=True),parser,provider)
    return TestClient(app),app,parser,provider

@pytest.mark.parametrize('task,calls',[('qa',2),('summary',4)])
def test_fresh_answers_no_disk_history_and_citations(tmp_path,task,calls):
    client,app,parser,provider=setup(tmp_path);doc=upload(client).json()['document_id'];before=state(tmp_path)
    for _ in range(2):
        response=client.post('/ask',json={'document_id':doc,'question':'retrieval evidence PRIVATE_TEST_QUESTION','task':task})
        assert response.status_code==200,response.text
        body=response.json();assert body['sources'] and body['answer']['citations']
        assert response.headers['cache-control']=='no-store' and not body['cache_hit']
        assert body['generation']['new_paid_generation'] and not body['generation']['recovered_existing_response']
        assert state(tmp_path)==before
        if task=='summary':assert all(s['within_10k'] for s in body['summary_diagnostics']['stages'] if s['budget_total'] is not None)
    assert provider.calls==calls and not (tmp_path/doc/'requests').exists() and not (tmp_path/doc/'responses').exists()
    assert upload(client).json()['cache_hit'] and parser.calls==1
    store=DocumentStore(tmp_path,parser);assert store.corpus(doc).bm25.cache_hit

def test_distinct_documents_and_index_cache(tmp_path):
    client,app,parser,_=setup(tmp_path);a=upload(client).json()['document_id'];b=upload(client,b'%PDF-other').json()['document_id']
    assert a!=b and parser.calls==2
    assert app.state.store.corpus(a).bm25.query('telescope')
    assert not app.state.store.corpus(b).bm25.query('telescope')

@pytest.mark.parametrize('content,status',[(b'bad',415),(b'%PDF-'+b'x'*100,413)])
def test_upload_validation(tmp_path,content,status):
    client=TestClient(create_app(Settings(data_dir=tmp_path,max_upload_bytes=40),SyntheticParser(),MockText()))
    assert upload(client,content).status_code==status

def test_generation_disabled_and_empty_question(tmp_path):
    client=TestClient(create_app(Settings(data_dir=tmp_path,generation_enabled=False),SyntheticParser(),MockText()))
    doc=upload(client).json()['document_id']
    assert client.post('/ask',json={'document_id':doc,'question':'retrieval evidence'}).status_code==503
    assert client.post('/ask',json={'document_id':doc,'question':' '}).status_code==422

def test_exact_10k_boundary():
    enforce_budget(6000,3900)
    with pytest.raises(ContextLimitError):enforce_budget(6001,3900)

def test_provider_rejects_over_budget_before_generation(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','offline-test-placeholder')
    paths=[]
    def transport(request):paths.append(request.url.path);return httpx.Response(200,json={'input_tokens':10000})
    provider=OpenAIText(approved=True,budget_usd=1,max_calls=2,transport=httpx.MockTransport(transport))
    with pytest.raises(ContextLimitError):provider.generate(make_request('test',[],max_output_tokens=100))
    assert paths==['/v1/responses/input_tokens'] and provider.calls==0
    provider.client.close()

def test_text_only_stateless_payload():
    request=make_request('test',[])
    assert request['store'] is False and request['truncation']=='disabled'
    assert 'previous_response_id' not in request and 'conversation' not in request
    assert all(c['type']=='input_text' for i in request['input'] for c in i['content'])

def test_relative_settings_and_env_loading(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('OPENAI_API_KEY=offline-test-placeholder\nENABLE_GENERATION=false\n',encoding='utf8')
    assert load_local_env(tmp_path) and os.environ['OPENAI_API_KEY']=='offline-test-placeholder'
    monkeypatch.setenv('RAG_DATA_DIR','data');monkeypatch.chdir(tmp_path)
    assert Settings().data_dir==ROOT/'data'
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)


@pytest.mark.parametrize('model',['', '  ', '  offline-custom-model  '])
def test_model_from_dotenv_at_startup(tmp_path,monkeypatch,model):
    import subprocess,sys
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    (tmp_path/'.env').write_text(f'OPENAI_MODEL="{model}"\n',encoding='utf8')
    script='''import sys
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from runtime_env import load_local_env
load_local_env(sys.argv[3])
from app.rag.core import MODEL,make_request,count_payload
request=make_request('offline',[])
assert request['model']==MODEL==count_payload(request)['model']
print(MODEL)
'''
    result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT/'backend'),str(ROOT/'scripts'),str(tmp_path)],
        capture_output=True,text=True,check=True)
    assert result.stdout.strip()==(model.strip() or 'gpt-5.4-mini-2026-03-17')


def test_model_environment_takes_precedence(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL','process-model')
    (tmp_path/'.env').write_text('OPENAI_MODEL=dotenv-model\n',encoding='utf8')
    assert load_local_env(tmp_path)
    assert os.environ['OPENAI_MODEL']=='process-model'

def test_error_does_not_persist_or_log_answer(tmp_path,caplog):
    class Failure(MockText):
        def generate(self,request):raise RuntimeError('PRIVATE_ANSWER_CONTENT')
    client,_,_,_=setup(tmp_path,Failure());doc=upload(client).json()['document_id'];before=state(tmp_path)
    response=client.post('/ask',json={'document_id':doc,'question':'retrieval evidence PRIVATE_TEST_QUESTION'})
    assert response.status_code==502 and state(tmp_path)==before
    assert 'PRIVATE_ANSWER_CONTENT' not in caplog.text

def test_real_docling_pdf_and_summary(tmp_path):
    models=Path(Settings().models_dir)
    if not models.is_dir():pytest.skip('Download Docling models first for this local integration test')
    from reportlab.pdfgen import canvas
    data=io.BytesIO();pdf=canvas.Canvas(data)
    pdf.drawString(60,750,'Local PDF retrieval evidence and source citations.')
    pdf.drawString(60,725,'The document explains methods and reproducible testing.');pdf.save()
    provider=MockText();client=TestClient(create_app(Settings(data_dir=tmp_path,generation_enabled=True),PDFParser(str(models)),provider))
    result=upload(client,data.getvalue());assert result.status_code==200,result.text
    doc=result.json()['document_id'];assert result.json()['chunks']>0
    assert upload(client,data.getvalue()).json()['cache_hit']
    for question in ('retrieval evidence','summary this document.'):
        response=client.post('/ask',json={'document_id':doc,'question':question})
        assert response.status_code==200,response.text
        assert response.json()['sources'] and response.json()['answer']['citations']


def test_all_application_modules_import():
    import importlib
    for path in (ROOT/'backend/app').rglob('*.py'):
        parts=list(path.relative_to(ROOT/'backend').with_suffix('').parts)
        if parts[-1]=='__init__':parts.pop()
        module=importlib.import_module('.'.join(parts))
        assert ROOT/'backend/app' in Path(module.__file__).resolve().parents or Path(module.__file__).resolve()==ROOT/'backend/app/__init__.py'


def test_archived_answers_are_never_read(tmp_path,monkeypatch):
    client,_,_,provider=setup(tmp_path);doc=upload(client).json()['document_id']
    trap=tmp_path/doc/'requests'/'old';trap.mkdir(parents=True)
    (trap/'raw-response.json').write_text('{"old":"ARCHIVED_ANSWER_MUST_NOT_APPEAR"}',encoding='utf8')
    before=state(tmp_path);read=Path.read_text
    def guarded(path,*args,**kwargs):
        if tmp_path in path.parents and any(part in ('requests','responses') for part in path.parts):
            raise AssertionError('A historical answer was read')
        return read(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    for task in ('qa','summary'):
        response=client.post('/ask',json={'document_id':doc,'question':'retrieval evidence','task':task})
        assert response.status_code==200,response.text
        assert 'ARCHIVED_ANSWER_MUST_NOT_APPEAR' not in response.text
        assert state(tmp_path)==before and not response.json()['cache_hit']
    assert provider.calls==3
