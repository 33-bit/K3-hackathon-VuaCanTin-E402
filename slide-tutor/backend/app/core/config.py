from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Folio Slide Tutor API"
    app_env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    database_url: str = "postgresql+asyncpg://slide_tutor:slide_tutor@localhost:5432/slide_tutor"
    redis_url: str = "redis://localhost:6379/0"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection_alias: str = "slide_chunks"
    qdrant_physical_collection: str = "slide_chunks_te3large_1536_bm25_v1"
    qdrant_timeout_seconds: float = 10.0

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-2024-08-06"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_dimensions: int = 1536
    embedding_version: str = "te3large_1536_v1"
    retrieval_schema_version: str = "qdrant_bm25_rrf_v1"
    openai_timeout_seconds: float = 60.0

    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 50 * 1024 * 1024
    allowed_upload_extensions: frozenset[str] = frozenset({".pdf", ".pptx"})
    dev_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    dev_course_id: UUID = UUID("00000000-0000-0000-0000-000000000010")
    auth_proxy_shared_secret: SecretStr | None = None

    embedding_batch_size: int = 64
    qdrant_upsert_batch_size: int = 64
    max_job_attempts: int = 5
    worker_poll_seconds: float = 1.0
    worker_lock_timeout_seconds: int = 1800
    reconcile_interval_seconds: int = 900
    old_vector_retention_seconds: int = 3600
    retrieval_prefetch_limit: int = 20
    retrieval_fused_limit: int = 12
    retrieval_context_limit: int = 6
    rerank_min_relevance: float = Field(default=0.35, ge=0, le=1)
    context_token_budget: int = Field(default=10_000, ge=1_000)
    conversation_history_turn_limit: int = Field(default=12, ge=0, le=50)
    conversation_history_token_budget: int = Field(default=6_000, ge=256, le=20_000)
    conversation_summary_token_budget: int = Field(default=800, ge=0, le=4_000)
    query_understanding_cache_ttl_seconds: int = 3600

    auto_create_schema: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("openai_embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, value: int) -> int:
        if value != 1536:
            raise ValueError("The v1 Qdrant collection requires exactly 1536 dimensions")
        return value

    @field_validator("openai_embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str) -> str:
        if value != "text-embedding-3-large":
            raise ValueError("The v1 Qdrant collection requires text-embedding-3-large")
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "test"}

    def ensure_runtime_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
