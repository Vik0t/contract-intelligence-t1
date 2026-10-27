from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration shared by the API and worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    database_url: str = "sqlite:///documents.db"
    document_storage_dir: Path = Path("uploads")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_size_mb: int = Field(default=50, ge=1, le=2048)
    max_pdf_pages: int = Field(default=200, ge=1, le=5000)
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    job_worker_count: int = Field(default=1, ge=1, le=4)
    job_stale_after_minutes: int = Field(default=30, ge=1, le=1440)
    extraction_backend: Literal["local", "huggingface-space", "api"] = "local"
    hf_space_id: str = "numind/NuExtract3"
    hf_space_api_name: str = "/on_extract_click"
    hf_space_prompt_mode: Literal["production", "compact"] = "compact"
    hf_space_context_mode: Literal["full", "retrieved"] = "retrieved"
    hf_space_context_chars: int = Field(default=3000, ge=500, le=10000)
    hf_space_reasoning: bool = False
    hf_extraction_fallback_enabled: bool = True
    hf_extraction_fallback_model: str = "Qwen/Qwen2.5-7B-Instruct:featherless-ai"

    @property
    def upload_limit_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
