from __future__ import annotations

from src.extraction.schema import (
    CONTRACT_TYPE_LABELS,
    TERM_SEMANTIC_TYPES,
    CONTRACT_TEMPLATE,
    INSTRUCTIONS,
)
from src.extraction.model_loading import (
    MODEL_ID,
    MODEL_QUANTIZATION_ENV,
    DEFAULT_MODEL_QUANTIZATION,
    EXTRACTION_BACKEND_ENV,
    IS_MACOS,
    MLX_AVAILABLE,
    ExtractionStats,
    get_extraction_stats,
    reset_extraction_stats,
    load_model,
    use_mlx,
)
from src.extraction.postprocess import (
    validate_extraction,
    postprocess_extraction,
)
from src.extraction.pipeline import (
    build_messages,
    parse_json_output,
    extract_text_from_document,
    extract_fields_from_text,
    extract_contract_key_data,
)

__all__ = [
    "CONTRACT_TYPE_LABELS",
    "TERM_SEMANTIC_TYPES",
    "CONTRACT_TEMPLATE",
    "INSTRUCTIONS",
    "MODEL_ID",
    "MODEL_QUANTIZATION_ENV",
    "DEFAULT_MODEL_QUANTIZATION",
    "EXTRACTION_BACKEND_ENV",
    "IS_MACOS",
    "MLX_AVAILABLE",
    "ExtractionStats",
    "get_extraction_stats",
    "reset_extraction_stats",
    "load_model",
    "use_mlx",
    "validate_extraction",
    "postprocess_extraction",
    "build_messages",
    "parse_json_output",
    "extract_text_from_document",
    "extract_fields_from_text",
    "extract_contract_key_data",
]