import logging
import json
import os
import time
from typing import Literal
from fastapi import FastAPI,File,UploadFile,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field
from .config import Settings
from .parser import PDFParser
from .store import DocumentStore,DocumentNotFound
from .service import RAGService,ExpandedUnavailable,GenerationDisabled
from .rag.core import ContextLimitError,GroundingError,IncompleteResponse
from .rag.provider import ApprovalRequired

log=logging.getLogger(__name__)

class AskRequest(BaseModel):
    document_id: str=Field(pattern=r'^[0-9a-f]{64}$')
    question: str=Field(min_length=1,max_length=4000)
    context_mode: Literal['baseline','expanded']|None=None
    task: Literal['auto','qa','summary']='auto'


def create_app(settings=None,parser=None,provider=None):
    settings=settings or Settings()
    store=DocumentStore(settings.data_dir,parser or PDFParser(settings.models_dir))
    service=RAGService(store,settings,provider)
    app=FastAPI(title='PDF Research Assistant',version='0.1.0')
    app.state.store=store;app.state.service=service

    @app.middleware('http')
    async def no_store_answers(request,call_next):
        response=await call_next(request)
        if request.url.path=='/ask':
            response.headers['Cache-Control']='no-store'
            response.headers['Pragma']='no-cache'
        return response

    @app.get('/health')
    def health():
        return {'status':'ok','context_modes':{'baseline':'available','expanded':'unavailable'},
            'generation_enabled':settings.generation_enabled,
            'api_key_configured':bool(os.getenv('OPENAI_API_KEY','').strip()),
            'max_upload_bytes':settings.max_upload_bytes}

    @app.post('/documents')
    def upload(file:UploadFile=File(...)):
        start=time.perf_counter()
        try:
            if not file.filename or not file.filename.lower().endswith('.pdf') or file.content_type!='application/pdf':
                raise HTTPException(415,'Upload must be a PDF with application/pdf content type')
            content=file.file.read(settings.max_upload_bytes+1)
            if len(content)>settings.max_upload_bytes:raise HTTPException(413,'PDF exceeds configured upload limit')
            if not content.startswith(b'%PDF-'):raise HTTPException(415,'Invalid PDF signature')
            result=store.ingest(content)
            return {**result,'elapsed_seconds':time.perf_counter()-start}
        except HTTPException:raise
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        except Exception as exc:
            log.error('PDF processing failed (%s)',type(exc).__name__)
            raise HTTPException(500,'PDF processing failed; check local models and server logs') from None
        finally:file.file.close()

    @app.post('/ask')
    def ask(request:AskRequest):
        start=time.perf_counter()
        if not request.question.strip():raise HTTPException(422,'Question must contain non-whitespace text')
        try:
            result=service.ask(request.document_id,request.question,request.context_mode or settings.context_mode,request.task)
            return {**result,'document_id':request.document_id,'elapsed_seconds':time.perf_counter()-start}
        except ExpandedUnavailable as exc:raise HTTPException(501,str(exc)) from None
        except DocumentNotFound as exc:raise HTTPException(404,str(exc)) from None
        except (GenerationDisabled,ApprovalRequired) as exc:raise HTTPException(503,str(exc)) from None
        except (GroundingError,IncompleteResponse,json.JSONDecodeError) as exc:
            return JSONResponse(status_code=422,content={'detail':str(exc),'validation_status':'rejected',
                'validation_warnings':[{'code':getattr(exc,'code','validation_rejected'),'message':str(exc),'severity':'rejected','source_ids':[]}]})
        except ContextLimitError as exc:raise HTTPException(422,str(exc)) from None
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        except Exception as exc:
            log.error('Answer generation failed (%s)',type(exc).__name__)
            raise HTTPException(502,'Generation failed; response was not accepted. Check server logs; no automatic retry.') from None
    return app

app=create_app()
