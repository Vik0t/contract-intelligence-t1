from __future__ import annotations

from functools import lru_cache
import importlib.util
import logging
import os
import platform
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor, BitsAndBytesConfig
from src.extraction.provenance import model_identity

load_dotenv()
logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("CONTRACT_MODEL_ID", "numind/NuExtract3")
MODEL_QUANTIZATION_ENV = "CONTRACT_MODEL_QUANTIZATION"
DEFAULT_MODEL_QUANTIZATION = "bf16"

# Явный переключатель бэкенда извлечения, независимый от автоопределения по ОС.
# "auto" — прежнее поведение (MLX на macOS, если доступен, иначе HF/transformers).
# "huggingface" — всегда идти через transformers, даже на macOS с установленным mlx-lm.
# "mlx" — принудительно использовать MLX (только на macOS).
EXTRACTION_BACKEND_ENV = "CONTRACT_EXTRACTION_BACKEND"

IS_MACOS = platform.system() == "Darwin"

if IS_MACOS:
    # Не импортируем mlx-lm при загрузке модуля: инициализация MLX требует
    # рабочего Metal-устройства и иначе будет валить старт тестов/API на хостах,
    # где инференс не используется.
    MLX_AVAILABLE = importlib.util.find_spec("mlx_lm") is not None
else:
    MLX_AVAILABLE = False


def use_mlx() -> bool:
    """Определяет, какой бэкенд использовать для инференса."""
    requested = os.getenv(EXTRACTION_BACKEND_ENV, "auto").strip().lower()
    if requested == "huggingface":
        return False
    if requested == "mlx":
        if not (IS_MACOS and MLX_AVAILABLE):
            raise RuntimeError(
                f"{EXTRACTION_BACKEND_ENV}=mlx запрошен, но mlx-lm недоступен на этой машине."
            )
        return True
    if requested != "auto":
        raise ValueError(
            f"{EXTRACTION_BACKEND_ENV} must be 'auto', 'huggingface' or 'mlx', got {requested!r}"
        )
    return IS_MACOS and MLX_AVAILABLE


class ExtractionStats:
    """Token usage statistics for extraction operations."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def add_usage(self, prompt_tokens: int, completion_tokens: int):
        """Add token usage from a single extraction."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens

    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


# Global stats collector
_stats_collector = ExtractionStats()
_loaded_model_provenance: dict[str, Any] = {}


def get_loaded_model_provenance() -> dict[str, Any]:
    return dict(_loaded_model_provenance) if load_model.cache_info().currsize else {}


def _snapshot_revision(path: Path) -> str | None:
    if path.parent.name == 'snapshots' and re.fullmatch(r'[0-9a-f]{40}', path.name):
        return path.name
    return None


def get_extraction_stats() -> dict:
    """Get current extraction statistics."""
    return _stats_collector.to_dict()


def reset_extraction_stats():
    """Reset extraction statistics."""
    global _stats_collector
    _stats_collector = ExtractionStats()


def record_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Records token usage into the global stats collector."""
    _stats_collector.add_usage(prompt_tokens, completion_tokens)


def _count_tokens_mlx(tokenizer, text: str) -> int:
    """Count tokens for MLX models."""
    try:
        return len(tokenizer.encode(text))
    except Exception:
        # Fallback to approximate counting
        return len(text.split())


@lru_cache(maxsize=1)
def load_model() -> tuple[Any, Any]:
    """Загружает модель один раз на процесс."""
    _loaded_model_provenance.clear()
    if use_mlx():
        from mlx_lm import load as mlx_load
        from huggingface_hub import snapshot_download

        model_id = os.getenv('CONTRACT_MLX_MODEL_ID', 'numind/NuExtract3-mlx-8bits')
        revision = os.getenv('CONTRACT_MLX_MODEL_REVISION') or None
        model_path = Path(model_id).expanduser()
        if not model_path.is_dir():
            # Match mlx-lm's supported files, resolve the ref once, and load
            # that immutable snapshot so provenance cannot race a moved ref.
            model_path = Path(snapshot_download(model_id, revision=revision, allow_patterns=[
                '*.json', 'model*.safetensors', '*.py', 'tokenizer.model',
                '*.tiktoken', 'tiktoken.model', '*.txt', '*.jsonl', '*.jinja',
            ]))
        model_path = model_path.resolve()
        model, tokenizer = mlx_load(str(model_path))
        resolved = _snapshot_revision(model_path)
        _loaded_model_provenance.update(model_identity(model_id, 'mlx', resolved,
            revision_source='snapshot' if resolved else 'unknown', requested_revision=revision))
        return model, tokenizer

    revision = os.getenv("CONTRACT_MODEL_REVISION") or None
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=revision, trust_remote_code=True)

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available() and not IS_MACOS:
        device = "mps"
    else:
        device = "cpu"

    requested_mode = os.getenv(MODEL_QUANTIZATION_ENV, DEFAULT_MODEL_QUANTIZATION).strip().lower()
    if requested_mode not in {"bf16", "8bit"}:
        raise ValueError(
            f"{MODEL_QUANTIZATION_ENV} must be 'bf16' or '8bit', got {requested_mode!r}"
        )

    if device == "cuda" and requested_mode == "bf16" and torch.cuda.is_bf16_supported():
        effective_mode = "bf16"
        dtype = torch.bfloat16
    elif device == "cuda":
        effective_mode = "8bit"
        dtype = torch.float16
        if requested_mode == "bf16":
            logger.warning("BF16 is unavailable on this CUDA device; falling back to 8-bit.")
    else:
        effective_mode = "full"
        dtype = torch.float32
        if requested_mode == "8bit":
            logger.warning(
                "8-bit quantization is only enabled for CUDA; using full precision on %s.",
                device,
            )

    model_kwargs = {
        "dtype": dtype,
        "device_map": device,
        "trust_remote_code": True,
        "revision": revision,
        "low_cpu_mem_usage": True,
    }
    if effective_mode == "8bit":
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_threshold=6.0,
        )

    logger.info(
        "Loading %s with mode=%s, device=%s, dtype=%s",
        MODEL_ID,
        effective_mode,
        device,
        dtype,
    )
    try:
        model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, **model_kwargs).eval()
    except (RuntimeError, TypeError, ValueError, OSError):
        if effective_mode != "bf16" or device != "cuda":
            raise
        logger.exception("BF16 model loading failed; retrying with 8-bit CUDA quantization.")
        torch.cuda.empty_cache()
        fallback_kwargs = {
            "dtype": torch.float16,
            "device_map": device,
            "quantization_config": BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
            ),
            "trust_remote_code": True,
            "revision": revision,
            "low_cpu_mem_usage": True,
        }
        model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, **fallback_kwargs).eval()
    config = getattr(model, 'config', None)
    resolved = getattr(config, '_commit_hash', None)
    local_path = Path(MODEL_ID).expanduser()
    source = 'model_config'
    if local_path.is_dir():
        resolved = _snapshot_revision(local_path.resolve())
        source = 'snapshot'
    elif not resolved and revision and re.fullmatch(r'[0-9a-f]{40}', revision):
        resolved = revision
        source = 'requested_commit'
    _loaded_model_provenance.update(model_identity(MODEL_ID, 'transformers', resolved,
        revision_source=source if resolved else 'unknown', requested_revision=revision))
    return processor, model


def unload_model() -> None:
    from src.extraction.runtime import MODEL_LOCK, release_device_memory
    with MODEL_LOCK:
        load_model.cache_clear()
        _loaded_model_provenance.clear()
        release_device_memory()
