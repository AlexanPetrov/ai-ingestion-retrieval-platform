"""Unit tests for outbound response-header admission checks."""

import pytest
from fastapi import HTTPException

from ai_ingestion_retrieval_platform.core.response_admission import (
    ERROR_CONTENT_TYPE_MISSING,
    ERROR_CONTENT_TYPE_UNSUPPORTED,
    ERROR_DECLARED_CONTENT_TOO_LARGE,
    normalize_content_type,
    parse_content_length,
    validate_allowed_content_type,
    validate_declared_content_length,
)


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        (None, None),
        ("text/html", "text/html"),
        (" Text/HTML; charset=UTF-8 ", "text/html"),
        ("   ", None),
    ],
)
def test_normalize_content_type(
    content_type: str | None,
    expected: str | None,
) -> None:
    assert normalize_content_type(content_type) == expected


@pytest.mark.parametrize(
    ("content_length", "expected"),
    [
        (None, None),
        ("123", 123),
        (" 456 ", 456),
        ("not-a-number", None),
        ("-1", None),
    ],
)
def test_parse_content_length(
    content_length: str | None,
    expected: int | None,
) -> None:
    assert parse_content_length(content_length) == expected


@pytest.mark.parametrize(
    ("content_length", "expected"),
    [
        (None, None),
        ("invalid", None),
        ("100", 100),
    ],
)
def test_validate_declared_content_length_accepts_missing_invalid_or_allowed_values(
    content_length: str | None,
    expected: int | None,
) -> None:
    assert validate_declared_content_length(content_length, max_bytes=100) == expected


def test_validate_declared_content_length_rejects_oversized_response() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_declared_content_length("101", max_bytes=100)

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == ERROR_DECLARED_CONTENT_TOO_LARGE


def test_validate_allowed_content_type_normalizes_and_accepts_supported_type() -> None:
    result = validate_allowed_content_type(
        " Text/HTML; charset=UTF-8 ",
        ("text/plain", "TEXT/HTML", " "),
    )

    assert result == "text/html"


@pytest.mark.parametrize("content_type", [None, "   "])
def test_validate_allowed_content_type_rejects_missing_type(
    content_type: str | None,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_allowed_content_type(
            content_type,
            ("text/plain", "text/html"),
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == ERROR_CONTENT_TYPE_MISSING


def test_validate_allowed_content_type_rejects_unsupported_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_allowed_content_type(
            "application/octet-stream",
            ("text/plain", "text/html"),
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == ERROR_CONTENT_TYPE_UNSUPPORTED
