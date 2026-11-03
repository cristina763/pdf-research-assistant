"""Load only documented settings; never print secret values."""
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'OPENAI_API_KEY','OPENAI_MODEL','ENABLE_GENERATION','CONTEXT_MODE','MAX_UPLOAD_MB','RAG_DATA_DIR','DOCLING_ARTIFACTS_PATH','GENERATION_BUDGET_USD','GENERATION_MAX_CALLS'}

def load_local_env(root=ROOT):
    path=Path(root)/'.env'
    if not path.is_file():return False
    values=dotenv_values(path,encoding='utf-8-sig',interpolate=False)
    unknown=set(values)-ALLOWED
    if unknown:raise ValueError('Unsupported .env setting; compare .env.example. Values are not printed.')
    for name,value in values.items():
        if value is None:raise ValueError('A .env setting has no value; check its format.')
        os.environ.setdefault(name,value)
    return True
