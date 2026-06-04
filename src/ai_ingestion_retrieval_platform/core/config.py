from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Ingestion & Retrieval Platform"
    log_level: str = "INFO"
    metrics_enabled: bool = False
    metrics_token: str | None = None

    http_timeout_connect_seconds: float = Field(default=2.0, gt=0)
    http_timeout_read_seconds: float = Field(default=5.0, gt=0)
    http_timeout_write_seconds: float = Field(default=5.0, gt=0)
    http_timeout_pool_seconds: float = Field(default=2.0, gt=0)
    max_redirects: int = Field(default=5, ge=0)
    max_preview_bytes: int = Field(default=65_536, ge=1)
    max_preview_text_chars: int = Field(default=500, ge=1)
    max_batch_urls: int = Field(default=20, ge=1)

    retry_attempts: int = Field(default=3, ge=1)
    retry_backoff_initial_seconds: float = Field(default=0.5, gt=0)
    retry_backoff_max_seconds: float = Field(default=4.0, gt=0)

    default_max_concurrency: int = Field(default=3, ge=1)
    max_allowed_concurrency: int = Field(default=10, ge=1)
    global_max_outbound_fetches: int = Field(default=20, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
