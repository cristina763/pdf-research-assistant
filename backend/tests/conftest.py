"""Self-contained tests: no external network and no real API credentials."""
import os,socket,sys,tempfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
os.environ['RAG_DATA_DIR']=tempfile.mkdtemp(prefix='rag-basic-')
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    connect=socket.socket.connect
    def blocked(sock,address):
        if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'):return connect(sock,address)
        raise AssertionError('External network is disabled in basic tests')
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
