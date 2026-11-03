import hashlib
import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from .rag.data import Corpus

CACHE_VERSION='docling-fast-bounded2048-v1'

class DocumentNotFound(ValueError):pass

class DocumentStore:
    def __init__(self,root,parser):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.parser=parser;self.lock=threading.RLock();self.corpora={}

    def _folder(self,document_id):
        if not re.fullmatch(r'[0-9a-f]{64}',document_id):raise DocumentNotFound('Unknown document_id')
        return self.root/document_id

    def ingest(self,content):
        document_id=hashlib.sha256(content).hexdigest();folder=self._folder(document_id)
        with self.lock:
            if (folder/'manifest.json').exists():
                m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
                if m['cache_version']!=CACHE_VERSION:raise ValueError('Incompatible document cache; reindex required')
                self.corpus(document_id)
                return {**m,'cache_hit':True}
            stage=self.root/('.upload-'+uuid.uuid4().hex);stage.mkdir()
            try:
                pdf=stage/'source.pdf';pdf.write_bytes(content)
                document,chunks,native=self.parser.parse(pdf,document_id)
                if not chunks:raise ValueError('PDF contains no searchable chunks')
                if any(c['document_id']!=document_id for c in chunks):raise ValueError('Cross-document chunk rejected')
                for name,value in [('document.json',document),('chunks.json',chunks),('native.json',native)]:
                    (stage/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
                Corpus(document,chunks,stage/'index')
                manifest={'document_id':document_id,'pages':document['source']['page_count'],
                    'chunks':len(chunks),'cache_version':CACHE_VERSION}
                (stage/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
                stage.rename(folder)
                return {**manifest,'cache_hit':False}
            finally:
                if stage.exists():shutil.rmtree(stage)

    def corpus(self,document_id):
        folder=self._folder(document_id)
        with self.lock:
            if not (folder/'manifest.json').is_file():raise DocumentNotFound('Unknown document_id; upload the PDF first')
            if document_id not in self.corpora:
                document=json.loads((folder/'document.json').read_text(encoding='utf-8'))
                chunks=json.loads((folder/'chunks.json').read_text(encoding='utf-8'))
                if document['document_id']!=document_id or any(c['document_id']!=document_id for c in chunks):
                    raise ValueError('Document cache identity mismatch')
                self.corpora[document_id]=Corpus(document,chunks,folder/'index')
            return self.corpora[document_id]
