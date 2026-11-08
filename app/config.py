from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.semantic import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANK_MODEL,
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
)

SemanticSetting = Literal["off", "on", "auto"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/app.db"

    max_upload_mb: float = Field(default=5, gt=0, le=50)
    max_pdf_pages: int = Field(default=10, gt=0, le=100)
    max_jd_chars: int = Field(default=20_000, gt=100)
    # DOCX files are zip archives. Cap the unpacked size to stop zip bombs.
    max_docx_uncompressed_mb: float = Field(default=50, gt=0)

    retention_hours: int = Field(default=24, gt=0)
    cors_origins: str = "http://localhost:8501"

    # Matching by meaning. "auto" turns it on only when sentence-transformers is
    # installed (the ml extra). "on" fails at startup if it isn't.
    semantic_matching: SemanticSetting = "auto"
    semantic_top_k: int = Field(default=DEFAULT_TOP_K, gt=0, le=50)
    semantic_threshold: float = Field(default=DEFAULT_THRESHOLD, ge=0, le=1)
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rerank_model: str = DEFAULT_RERANK_MODEL

    anthropic_api_key: SecretStr | None = None

    @field_validator("semantic_matching", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def max_docx_uncompressed_bytes(self) -> int:
        return int(self.max_docx_uncompressed_mb * 1024 * 1024)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
