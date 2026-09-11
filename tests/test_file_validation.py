from pathlib import Path

import pymupdf
import pytest

from backend.file_validation import UploadValidationError, validate_document_file


def test_pdf_signature_and_page_limit(tmp_path: Path) -> None:
    path = tmp_path / "document.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()

    validate_document_file(path, ".pdf", max_pdf_pages=1)
    with pytest.raises(UploadValidationError, match="слишком много"):
        validate_document_file(path, ".pdf", max_pdf_pages=0)


def test_invalid_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "document.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(UploadValidationError, match="корректным PDF"):
        validate_document_file(path, ".pdf", max_pdf_pages=10)


def test_docx_signature_and_structure_are_checked(tmp_path: Path) -> None:
    path = tmp_path / "document.docx"
    path.write_bytes(b"PK\x03\x04not a zip")

    with pytest.raises(UploadValidationError, match="корректным DOCX"):
        validate_document_file(path, ".docx", max_pdf_pages=10)
