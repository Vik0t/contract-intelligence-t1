from pathlib import Path
import shutil

import pymupdf
import pytest
from docx import Document

from backend.document_view import locate_evidence, page_count, render_page


def test_pdf_renders_original_page_and_locates_exact_fragment(tmp_path):
    path = tmp_path / "source.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 100), "First page")
    pdf.new_page().insert_text((72, 350), "Unique contract clause")
    pdf.save(path)
    pdf.close()

    assert page_count(path) == 2
    location = locate_evidence(path, "Unique contract clause", preferred_page=1)
    assert location["page"] == 2
    assert 0.3 < location["rects"][0]["y"] < 0.5
    assert render_page(path, 2).startswith(b"\x89PNG")


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice unavailable")
def test_docx_uses_real_rendered_pages(tmp_path):
    path = tmp_path / "formatted.docx"
    document = Document()
    document.add_paragraph("First contract page")
    document.add_page_break()
    document.add_paragraph("Unique second page clause")
    document.save(path)

    assert page_count(path) == 2
    location = locate_evidence(path, "Unique second page clause", preferred_page=1)
    assert location["page"] == 2
    assert Path(str(path) + ".rendered.pdf").is_file()
