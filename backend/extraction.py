"""Runtime selection between local and hosted extraction backends."""

from __future__ import annotations

from typing import Any
import logging

from backend.config import Settings
from src.document_ir import DocumentIR
from src.hf_space_extraction import HFSpaceNuExtractBackend
from src.hf_chat_extraction import extract_fields_with_hf_chat
from src.local_extraction import extract_contract_key_data, reset_extraction_stats

logger = logging.getLogger(__name__)


class ExtractionService:
    """Keep backend selection and token accounting in one place."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hf_space_backend: HFSpaceNuExtractBackend | None = None

    @property
    def backend_name(self) -> str:
        return self.settings.extraction_backend

    def _get_hf_space_backend(self) -> HFSpaceNuExtractBackend:
        if self._hf_space_backend is None:
            self._hf_space_backend = HFSpaceNuExtractBackend(
                space_id=self.settings.hf_space_id,
                api_name=self.settings.hf_space_api_name,
            )
        return self._hf_space_backend

    def extract(
        self,
        *,
        text: str,
        document_ir: DocumentIR | None = None,
        max_new_tokens: int = 4096,
        collect_stats: bool = True,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Extract contract fields using the configured runtime backend."""
        if self.settings.extraction_backend == "local":
            reset_extraction_stats()
            return extract_contract_key_data(
                text=text,
                document_ir=document_ir,
                max_new_tokens=max_new_tokens,
                collect_stats=collect_stats,
            )

        if self.settings.extraction_backend == "huggingface-space":
            try:
                result = self._get_hf_space_backend().extract_fields_from_text(
                    text,
                    document_ir,
                    prompt_mode=self.settings.hf_space_prompt_mode,
                    context_mode=self.settings.hf_space_context_mode,
                    context_chars=self.settings.hf_space_context_chars,
                    reasoning=self.settings.hf_space_reasoning,
                )
            except Exception as space_error:
                if not self.settings.hf_extraction_fallback_enabled:
                    raise
                logger.warning(
                    "NuExtract Space failed (%s); trying Hugging Face chat extraction",
                    type(space_error).__name__,
                )
                try:
                    fallback_result, fallback_usage = extract_fields_with_hf_chat(
                        text,
                        document_ir,
                        model=self.settings.hf_extraction_fallback_model,
                        context_chars=self.settings.hf_space_context_chars,
                    )
                except Exception as fallback_error:
                    raise RuntimeError(
                        "NuExtract Space и резервное извлечение Hugging Face недоступны"
                    ) from fallback_error
                if not collect_stats:
                    return fallback_result, {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    }
                return fallback_result, fallback_usage
            if not collect_stats:
                return result.result, {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            usage = result.usage
            return result.result, {
                "prompt_tokens": usage.estimated_input_tokens,
                "completion_tokens": usage.estimated_output_tokens,
                "total_tokens": usage.estimated_input_tokens
                + usage.estimated_output_tokens,
            }

        raise ValueError(
            "Unsupported extraction backend: "
            f"{self.settings.extraction_backend}"
        )
