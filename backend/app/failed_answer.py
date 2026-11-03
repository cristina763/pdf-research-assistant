"""Safe display of public model output after independent validation failure."""
import json
import os
import re
from .rag.core import GroundingError


def readable_output(text):
    try: payload=json.loads(text)
    except (ValueError,TypeError):
        # Never show malformed structured payloads or arbitrary reasoning fields.
        if not isinstance(text,str) or text.lstrip().startswith(('{','[')):return ''
        payload={'answer_markdown':text}
    if not isinstance(payload,dict):return ''
    blocks=[]
    if isinstance(payload.get('sections'),list):
        for section in payload['sections']:
            if not isinstance(section,dict):continue
            statements=section.get('statements',[])
            if not isinstance(statements,list):continue
            for statement in statements:
                if isinstance(statement,dict) and isinstance(statement.get('text'),str):blocks.append(statement['text'])
    if not blocks:
        for key in ('answer_markdown','answer','final_answer'):
            if isinstance(payload.get(key),str):blocks=[payload[key]];break
    result='\n\n'.join(block.strip() for block in blocks if block.strip())
    result=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]',result)
    key=os.getenv('OPENAI_API_KEY','')
    if key:result=result.replace(key,'[REDACTED]')
    return result


def failed_answer(text,error):
    readable=readable_output(text)
    if not readable:raise GroundingError('No readable public model answer; raw response retained locally')
    warning={'code':getattr(error,'code','quality_contract_failed'),'message':str(error),
        'severity':'rejected','source_ids':[]}
    return {'answer_markdown':readable,'citations':[],'numeric_claims':[],
        'covered_source_ids':[],'limitations':[],'evidence_status':'unverified',
        'failed_validation':{'output_text':text,'warning':warning}}
