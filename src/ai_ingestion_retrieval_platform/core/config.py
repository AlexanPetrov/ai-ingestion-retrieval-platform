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

    http_timeout_seconds: float = Field(default=5.0, gt=0)
    retry_attempts: int = Field(default=3, ge=1)
    retry_backoff_initial_seconds: float = Field(default=0.5, gt=0)
    retry_backoff_max_seconds: float = Field(default=4.0, gt=0)

    default_max_concurrency: int = Field(default=3, ge=1)
    max_allowed_concurrency: int = Field(default=10, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
