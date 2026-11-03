"""Portable local entry point; .env is loaded before app imports."""
import argparse,json,os,sys
from runtime_env import ROOT,load_local_env

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--check-config',action='store_true')
    args=parser.parse_args();load_local_env()
    sys.path.insert(0,str(ROOT/'backend'))
    if args.check_config:
        from app.config import Settings
        from app.rag.core import MODEL,CONTEXT_LIMIT
        settings=Settings()
        print(json.dumps({'generation_enabled':settings.generation_enabled,'api_key_present':bool(os.getenv('OPENAI_API_KEY','').strip()),'model':MODEL,'context_limit':CONTEXT_LIMIT,'host':args.host,'port':args.port}))
        return
    import uvicorn
    uvicorn.run('app.main:app',host=args.host,port=args.port,log_level='info')

if __name__=='__main__':main()
