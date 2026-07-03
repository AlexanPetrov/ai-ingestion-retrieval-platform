"""Unit tests for HTTPException -> typed ingestion error mapping."""

import pytest
from fastapi import HTTPException

from ai_ingestion_retrieval_platform.services import ingestion as ingestion_service


@pytest.mark.parametrize(
    ("status_code", "detail", "expected_code"),
    [
        (400, ingestion_service.ERROR_TOO_MANY_REDIRECTS, "too_many_redirects"),
        (
            400,
            ingestion_service.ERROR_REDIRECT_MISSING_LOCATION,
            "redirect_error",
        ),
        (400, "Only http and https URLs are allowed", "unsupported_url_scheme"),
        (400, "URL credentials are not allowed", "url_credentials_not_allowed"),
        (400, "URL port is not allowed", "url_port_not_allowed"),
        (400, "URL port is invalid", "url_port_invalid"),
        (400, "Private/internal IP URLs are not allowed", "unsafe_url"),
        (504, ingestion_service.ERROR_TIMEOUT, "timeout"),
        (502, "URL returned HTTP 503", "http_status"),
        (502, ingestion_service.ERROR_FETCH_FAILED, "network_error"),
        (418, "teapot", "unknown_error"),
    ],
)
def test_build_ingestion_error_maps_to_expected_error_code(
    status_code: int,
    detail: str,
    expected_code: str,
) -> None:
    exc = HTTPException(status_code=status_code, detail=detail)

    result = ingestion_service.build_ingestion_error(exc)

    assert result.code == expected_code
    assert result.message == detail
    assert result.status_code == status_code
