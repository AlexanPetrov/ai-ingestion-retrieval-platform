"""Environment-backed runtime settings and safety limits."""

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application and metrics settings
    # main.py, core/logging.py, api/routes/metrics.py
    app_name: str = "AI Ingestion & Retrieval Platform"  # FastAPI app title.
    log_level: str = "INFO"  # Minimum log level.
    metrics_enabled: bool = False  # Enable or hide /metrics endpoint.
    metrics_token: str | None = None  # Bearer token for /metrics access.

    # Ingestion API authentication
    # api/dependencies/auth.py, api/routes/ingestion.py
    ingestion_auth_enabled: bool = False  # Require bearer auth on ingestion routes.
    ingestion_auth_token: str | None = None  # Bearer token for ingestion access.

    # Timeouts
    # main.py
    http_timeout_connect_seconds: float = Field(
        default=2.0, gt=0
    )  # Max time to open connection.
    http_timeout_read_seconds: float = Field(
        default=5.0, gt=0
    )  # Max wait between response chunks.
    http_timeout_write_seconds: float = Field(
        default=5.0, gt=0
    )  # Max time to send request data.
    http_timeout_pool_seconds: float = Field(
        default=2.0, gt=0
    )  # Max wait for free pooled connection.

    # Connection pool limits
    # main.py
    http_max_connections: int = Field(
        default=20, ge=1
    )  # Max total outbound HTTP connections.
    http_max_keepalive_connections: int = Field(
        default=10, ge=1
    )  # Max idle reusable connections.
    http_keepalive_expiry_seconds: float = Field(
        default=30.0, gt=0
    )  # How long idle connections stay open.

    # Ingestion safety and preview limits
    # services/ingestion.py, api/routes/ingestion.py, core/url_safety.py
    max_redirects: int = Field(default=5, ge=0)  # Max redirect hops per URL fetch.
    max_preview_bytes: int = Field(default=65_536, ge=1)  # Max response bytes to read.
    max_preview_text_chars: int = Field(default=500, ge=1)  # Max preview text returned.
    max_batch_urls: int = Field(
        default=20, ge=1
    )  # Max URLs accepted per batch request.
    allowed_fetch_ports: tuple[int, ...] = (80, 443)  # Allowed outbound URL ports.

    # Parser boundary limits
    # services/ingestion.py, services/parsing.py
    max_parse_bytes: int = Field(default=5_000_000, ge=1)  # Max bytes sent to parser.
    max_parsed_text_chars: int = Field(
        default=100_000, ge=1
    )  # Max parsed text returned.
    max_parse_pages: int = Field(default=50, ge=1)  # Max PDF pages to parse.
    parse_timeout_seconds: float = Field(default=10.0, gt=0)  # Max parser runtime.
    allowed_parse_content_types: tuple[str, ...] = (
        "text/html",
        "text/plain",
        "application/pdf",
    )  # Content types allowed for parsing.

    # Retry and per-URL timeout policy
    # services/ingestion.py
    retry_attempts: int = Field(default=3, ge=1)  # Max retry attempts per URL fetch.
    retry_total_timeout_seconds: float = Field(
        default=10.0, gt=0
    )  # Max total retry time.
    retry_backoff_initial_seconds: float = Field(
        default=0.5, gt=0
    )  # First backoff delay.
    retry_backoff_max_seconds: float = Field(default=4.0, gt=0)  # Max backoff delay.
    url_timeout_seconds: float = Field(default=10.0, gt=0)  # Max total time per URL.

    # Concurrency and limiter controls
    # api/routes/ingestion.py, services/ingestion.py, core/limits.py
    default_max_concurrency: int = Field(default=3, ge=1)  # Default batch concurrency.
    max_allowed_concurrency: int = Field(
        default=10, ge=1
    )  # Max client-requested concurrency.
    global_max_outbound_fetches: int = Field(
        default=24, ge=1
    )  # Max outbound fetches per process.
    host_max_concurrency: int = Field(
        default=3, ge=1
    )  # Max concurrent fetches per host.
    host_limiter_cache_size: int = Field(
        default=1024, ge=1
    )  # Max host limiters cached.

    # Inbound API rate limiting
    # main.py, api/dependencies/rate_limit.py, api/routes/ingestion.py
    rate_limit_enabled: bool = False  # Enable inbound API rate limiting.
    rate_limit_redis_url: str = "redis://localhost:6379/0"  # Redis limiter store.
    rate_limit_key_prefix: str = "ai-irp:rate-limit"  # Redis key prefix.
    rate_limit_fail_open: bool = False  # Allow requests if limiter storage fails.
    rate_limit_url_preview_requests: int = Field(
        default=30, ge=1
    )  # Single URL preview requests per window.
    rate_limit_url_preview_window_seconds: int = Field(
        default=60, ge=1
    )  # Single URL preview window size.
    rate_limit_batch_preview_requests: int = Field(
        default=10, ge=1
    )  # Batch preview requests per window.
    rate_limit_batch_preview_window_seconds: int = Field(
        default=60, ge=1
    )  # Batch preview window size.
    rate_limit_url_preview_cost: int = Field(
        default=1, ge=1
    )  # Cost for raw single-URL preview.
    rate_limit_url_parse_preview_cost: int = Field(
        default=2, ge=1
    )  # Cost for parsed single-URL preview.
    rate_limit_batch_preview_url_cost: int = Field(
        default=1, ge=1
    )  # Cost per URL in raw batch preview.
    rate_limit_batch_parse_preview_url_cost: int = Field(
        default=2, ge=1
    )  # Cost per URL in parsed batch preview.

    @model_validator(mode="after")
    def validate_setting_relationships(self) -> Self:
        """Reject contradictory or incomplete runtime configuration."""
        if self.default_max_concurrency > self.max_allowed_concurrency:
            raise ValueError(
                "default_max_concurrency cannot exceed max_allowed_concurrency"
            )

        if self.http_max_keepalive_connections > self.http_max_connections:
            raise ValueError(
                "http_max_keepalive_connections cannot exceed http_max_connections"
            )

        if self.retry_backoff_initial_seconds > self.retry_backoff_max_seconds:
            raise ValueError(
                "retry_backoff_initial_seconds cannot exceed retry_backoff_max_seconds"
            )

        if self.ingestion_auth_enabled and not (
            self.ingestion_auth_token and self.ingestion_auth_token.strip()
        ):
            raise ValueError(
                "ingestion_auth_token is required when ingestion_auth_enabled is true"
            )

        if self.metrics_enabled and not (
            self.metrics_token and self.metrics_token.strip()
        ):
            raise ValueError("metrics_token is required when metrics_enabled is true")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
