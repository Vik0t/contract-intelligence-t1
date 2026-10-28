"""Shared parsing path for the upload worker and direct evaluation."""
from pathlib import Path

from backend.document_view import view_pdf_path
from src.document_ir import SourceFormat
from src.ocr import TesseractOCRBackend
from src.parsing import parse_document, document_ir_to_text


def parse_for_extraction(path, settings):
    source = Path(path)
    parse_path = source
    if source.suffix.lower() == '.docx' and settings.docx_use_rendered_pages:
        parse_path = view_pdf_path(source)
    # Photos remain an optional feature of custom profiles. The PMI profile
    # accepts only PDF/DOCX and never constructs an OCR backend.
    use_ocr = settings.allow_ocr_uploads or (
        settings.delivery_profile == 'custom' and source.suffix.lower() in {'.jpg', '.jpeg', '.png'})
    document = parse_document(parse_path, ocr_backend=TesseractOCRBackend() if use_ocr else None)
    if parse_path != source:
        document.source_format = SourceFormat.DOCX
        document.source_path = str(source)
    return document_ir_to_text(document), document
