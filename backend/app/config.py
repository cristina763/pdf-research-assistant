import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def project_path(value):
    path=Path(value)
    return (path if path.is_absolute() else ROOT/path).resolve()

@dataclass
class Settings:
    data_dir: Path=field(default_factory=lambda:project_path(os.getenv('RAG_DATA_DIR','data')))
    models_dir: str=field(default_factory=lambda:str(project_path(os.getenv('DOCLING_ARTIFACTS_PATH','models'))))
    max_upload_bytes: int=field(default_factory=lambda:int(os.getenv('MAX_UPLOAD_MB','30'))*1024*1024)
    context_mode: str=field(default_factory=lambda:os.getenv('CONTEXT_MODE','baseline'))
    generation_enabled: bool=field(default_factory=lambda:os.getenv('ENABLE_GENERATION','false').lower()=='true')
    budget_usd: float=field(default_factory=lambda:float(os.getenv('GENERATION_BUDGET_USD','1')))
    max_calls: int=field(default_factory=lambda:int(os.getenv('GENERATION_MAX_CALLS','40')))

    def __post_init__(self):
        if self.context_mode not in ('baseline','expanded'):raise ValueError('CONTEXT_MODE must be baseline or expanded')
        if self.max_upload_bytes<1:raise ValueError('Upload size must be positive')
