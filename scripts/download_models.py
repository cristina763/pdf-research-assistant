"""Download Docling parser models from the official package's public sources."""
import sys
from pathlib import Path
from runtime_env import ROOT,load_local_env

def main():
    load_local_env();sys.path.insert(0,str(ROOT/'backend'))
    from app.config import Settings
    from docling.utils.model_downloader import download_models
    folder=Path(Settings().models_dir)
    download_models(output_dir=folder,with_code_formula=False,with_picture_classifier=False,with_rapidocr=False)
    print('Docling parser model download completed. No LLM API was called.')

if __name__=='__main__':main()
