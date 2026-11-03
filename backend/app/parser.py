import os
from pathlib import Path
from .rag.preprocess import build

class PDFParser:
    def __init__(self,models_dir=''):
        self.models_dir=models_dir
        self.converter=None

    def parse(self,path,document_id):
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat, ConversionStatus
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        if self.converter is None:
            if not self.models_dir or not Path(self.models_dir).is_dir():
                raise ValueError('Local Docling models missing. Download models first and set DOCLING_ARTIFACTS_PATH.')
            import docling_parse
            if os.name=='nt' and not str(Path(docling_parse.__file__).resolve().parent).isascii():
                raise ValueError('Docling native resources require an ASCII-only virtual environment path on Windows. Recreate .venv in a path without Chinese or other non-ASCII characters.')
            options=PdfPipelineOptions(do_ocr=False,do_table_structure=True,
                table_structure_options=TableStructureOptions(mode=TableFormerMode.FAST,do_cell_matching=True),
                accelerator_options=AcceleratorOptions(device='cpu',num_threads=4),
                artifacts_path=Path(self.models_dir),do_code_enrichment=False,do_formula_enrichment=False,
                do_picture_description=False,do_picture_classification=False,
                enable_remote_services=False,allow_external_plugins=False)
            self.converter=DocumentConverter(allowed_formats=[InputFormat.PDF],
                format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)})
        result=self.converter.convert(path)
        if result.status!=ConversionStatus.SUCCESS:raise ValueError('Docling could not completely parse this PDF')
        document,chunks=build(result.document,document_id)
        return document,chunks,result.document.export_to_dict()
