"""Small local retrievers. No evaluation-question or answer-key dependency."""
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np



def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


STOPWORDS=set('a an the and or of to in for with is are was were what which how does do on from by this that as it its'.split())


def tokenize(text):
    words=re.findall(r'-?[a-z]+(?:-[a-z]+)*|\d+(?:\.\d+)?%?',text.casefold())
    result=[w for w in words if w not in STOPWORDS]
    for w in words:
        if '-' in w.lstrip('-'): result.extend(p for p in w.strip('-').split('-') if p not in STOPWORDS)
    return result


def corpus_key(chunks):return fingerprint([{'chunk_id':c['chunk_id'],'text':c['text']} for c in chunks])


def ranked(scores,chunks,k,positive_only=False):
    if k<1: raise ValueError('k must be positive')
    order=sorted(range(len(chunks)),key=lambda i:(-float(scores[i]),chunks[i]['chunk_id']))
    return [{'chunk_id':chunks[i]['chunk_id'],'score':float(scores[i]),'rank':r+1}
            for r,i in enumerate([i for i in order if not positive_only or scores[i]>0][:k])]


class BM25:
    def __init__(self,chunks,cache=None,k1=1.2,b=0.75):
        tick=time.perf_counter();self.chunks=chunks;self.k1=k1;self.b=b
        self.key=fingerprint({'corpus':corpus_key(chunks),'tokenizer':'english_regex_compounds_v1','k1':k1,'b':b})
        folder=Path(cache)/('bm25-'+self.key)
        self.cache_hit=(folder/'metadata.json').exists()
        if self.cache_hit:
            m=read_json(folder/'metadata.json');self.vocab=m['vocab']
            with np.load(folder/'index.npz',allow_pickle=False) as d:self.tf=d['tf'];self.idf=d['idf'];self.length=d['length']
        else:
            counters=[Counter(tokenize(c['text'])) for c in chunks]
            self.vocab=sorted({t for c in counters for t in c})
            self.tf=np.array([[c[t] for t in self.vocab] for c in counters],dtype=np.float32)
            self.length=np.array([sum(c.values()) for c in counters],dtype=np.float32)
            df=(self.tf>0).sum(axis=0)
            self.idf=np.log1p((len(chunks)-df+0.5)/(df+0.5))
            folder.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(folder/'index.npz',tf=self.tf,idf=self.idf,length=self.length)
            save_json(folder/'metadata.json',{'vocab':self.vocab,'key':self.key,'k1':k1,'b':b})
        self.term_index={t:i for i,t in enumerate(self.vocab)}
        self.norm=self.k1*(1-self.b+self.b*self.length/max(float(self.length.mean()),1))
        self.build_or_load_seconds=time.perf_counter()-tick
        self.numeric_buffer_bytes=self.tf.nbytes+self.idf.nbytes+self.length.nbytes+self.norm.nbytes
        self.cache_folder=folder

    def query(self,text,k=5):
        score=np.zeros(len(self.chunks),dtype=np.float64)
        for word,qtf in Counter(tokenize(text)).items():
            if word in self.term_index:
                i=self.term_index[word];tf=self.tf[:,i]
                score+=qtf*self.idf[i]*tf*(self.k1+1)/(tf+self.norm)
        return ranked(score,self.chunks,k,positive_only=True)
