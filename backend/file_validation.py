from __future__ import annotations

from pathlib import Path
import zipfile

import fitz


class UploadValidationError(ValueError):
    """Raised when an uploaded document is unsafe or unsupported."""


def validate_document_file(path: str | Path, extension: str, *, max_pdf_pages: int) -> None:
    """Validate the file signature and basic document limits before persistence."""
    document_path = Path(path)
    if not document_path.is_file() or document_path.stat().st_size == 0:
        raise UploadValidationError("Файл пустой или недоступен")

    extension = extension.lower()
    with document_path.open("rb") as stream:
        header = stream.read(8)

    if extension == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise UploadValidationError("Файл не является корректным PDF")
        try:
            with fitz.open(document_path) as pdf:
                if len(pdf) > max_pdf_pages:
                    raise UploadValidationError(
                        f"PDF содержит слишком много страниц: максимум {max_pdf_pages}"
                    )
        except UploadValidationError:
            raise
        except Exception as exc:
            raise UploadValidationError("PDF повреждён или не может быть прочитан") from exc
        return

    if extension == ".docx":
        if not header.startswith(b"PK") or not zipfile.is_zipfile(document_path):
            raise UploadValidationError("Файл не является корректным DOCX")
        try:
            with zipfile.ZipFile(document_path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise UploadValidationError("DOCX не содержит основной документ")
        except UploadValidationError:
            raise
        except Exception as exc:
            raise UploadValidationError("DOCX повреждён или не может быть прочитан") from exc
        return

    raise UploadValidationError("Поддерживаются только PDF и DOCX")
