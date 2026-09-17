from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    IMAGE = "image"

class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"

class BlockSource(StrEnum):
    DIGITAL = "digital"
    OCR = "ocr"
    DOCX = "docx"

class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        if self.x1 <= self.x0:
            raise ValueError("x1 должен быть больше x0")

        if self.y1 <= self.y0:
            raise ValueError("y1 должен быть больше y0")

        return self

class BlockIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: BlockKind
    text: str = Field(min_length=1)

    source: BlockSource
    bbox: BBox | None = None
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    raw_label: str | None = None
    order: int | None = Field(
        default=None,
        ge=0,
    )

class PageIR(BaseModel):
    needs_ocr: bool = False
    model_config = ConfigDict(extra="forbid")

    number: int | None = Field(default=None, ge=1)

    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)

    image_ref: str | None = None
    blocks: list[BlockIR] = Field(default_factory=list)


class DocumentIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_format: SourceFormat
    source_path: str

    page_count: int | None = Field(default=None, ge=1)
    pages: list[PageIR] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_page_count(self) -> Self:
        if self.page_count is not None:
            if self.page_count != len(self.pages):
                raise ValueError(
                    "page_count должен совпадать с количеством pages"
                )

        return self




if __name__ == "__main__":
    document = DocumentIR(
        source_format="pdf",
        source_path="dataset/Договор_001.pdf",
        page_count=1,
        pages=[
            {
                "number": 1,
                "width": 595,
                "height": 842,
                "blocks": [
                    {
                        "id": "page-1-block-1",
                        "kind": "paragraph",
                        "text": "Договор поставки № 15",
                        "source": "digital",
                        "bbox": {
                            "x0": 72,
                            "y0": 100,
                            "x1": 420,
                            "y1": 130,
                        },
                    }
                ],
            }
        ],
    )


    print(document.model_dump_json(indent=2))
