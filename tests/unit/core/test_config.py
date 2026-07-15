"""Unit tests for runtime settings validation."""

import pytest
from pydantic import ValidationError

from ai_ingestion_retrieval_platform.core.config import Settings


def test_settings_accept_valid_cross_setting_relationships() -> None:
    settings = Settings(
        _env_file=None,
        default_max_concurrency=3,
        max_allowed_concurrency=10,
        http_max_connections=20,
        http_max_keepalive_connections=10,
        retry_backoff_initial_seconds=0.5,
        retry_backoff_max_seconds=4.0,
        ingestion_auth_enabled=True,
        ingestion_auth_token="ingestion-token",
        metrics_enabled=True,
        metrics_token="metrics-token",
    )

    assert settings.default_max_concurrency == 3
    assert settings.max_allowed_concurrency == 10


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {
                "default_max_concurrency": 11,
                "max_allowed_concurrency": 10,
            },
            "default_max_concurrency cannot exceed max_allowed_concurrency",
        ),
        (
            {
                "http_max_connections": 10,
                "http_max_keepalive_connections": 11,
            },
            ("http_max_keepalive_connections cannot exceed http_max_connections"),
        ),
        (
            {
                "retry_backoff_initial_seconds": 5.0,
                "retry_backoff_max_seconds": 4.0,
            },
            ("retry_backoff_initial_seconds cannot exceed retry_backoff_max_seconds"),
        ),
    ],
)
def test_settings_reject_contradictory_numeric_relationships(
    overrides: dict[str, int | float],
    expected_message: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        Settings(
            _env_file=None,
            **overrides,
        )


@pytest.mark.parametrize("token", [None, "", "   "])
def test_settings_require_token_when_ingestion_auth_is_enabled(
    token: str | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match=("ingestion_auth_token is required when ingestion_auth_enabled is true"),
    ):
        Settings(
            _env_file=None,
            ingestion_auth_enabled=True,
            ingestion_auth_token=token,
        )


@pytest.mark.parametrize("token", [None, "", "   "])
def test_settings_require_token_when_metrics_are_enabled(
    token: str | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match="metrics_token is required when metrics_enabled is true",
    ):
        Settings(
            _env_file=None,
            metrics_enabled=True,
            metrics_token=token,
        )
