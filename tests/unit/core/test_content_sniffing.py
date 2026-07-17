"""Unit tests for byte-level content sniffing."""

import pytest
from fastapi import HTTPException

from ai_ingestion_retrieval_platform.core.content_sniffing import (
    ERROR_CONTENT_BYTES_MISMATCH,
    validate_content_matches_declared_type,
)


@pytest.mark.parametrize(
    "content",
    [
        b"%PDF-1.7\n",
        b"\n\r\t %PDF-1.4\n",
        b"\xef\xbb\xbf%PDF-1.5\n",
    ],
)
def test_validate_content_matches_declared_type_accepts_pdf_bytes(
    content: bytes,
) -> None:
    validate_content_matches_declared_type(content, "application/pdf")


def test_validate_content_matches_declared_type_rejects_non_pdf_bytes() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_content_matches_declared_type(
            b"<html><body>not a pdf</body></html>",
            "application/pdf",
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == ERROR_CONTENT_BYTES_MISMATCH


@pytest.mark.parametrize(
    "content",
    [
        b"<!doctype html><html></html>",
        b"<html><body>Hello</body></html>",
        b"\n\t<body>Hello</body>",
        b"<!-- comment --><html><body>Hello</body></html>",
    ],
)
def test_validate_content_matches_declared_type_accepts_html_bytes(
    content: bytes,
) -> None:
    validate_content_matches_declared_type(content, "text/html; charset=utf-8")


def test_validate_content_matches_declared_type_rejects_non_html_bytes() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_content_matches_declared_type(b"plain text only", "text/html")

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == ERROR_CONTENT_BYTES_MISMATCH


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"plain text",
        "unicode text \u2603".encode(),
        b"line one\nline two\tindented",
    ],
)
def test_validate_content_matches_declared_type_accepts_text_bytes(
    content: bytes,
) -> None:
    validate_content_matches_declared_type(content, "text/plain")


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe\x00\x00",
        b"hello\x00world",
    ],
)
def test_validate_content_matches_declared_type_rejects_binary_text_bytes(
    content: bytes,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_content_matches_declared_type(content, "text/plain")

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == ERROR_CONTENT_BYTES_MISMATCH


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "",
        "application/json",
        "application/octet-stream",
    ],
)
def test_validate_content_matches_declared_type_ignores_unchecked_types(
    content_type: str | None,
) -> None:
    validate_content_matches_declared_type(b"\x00\x01\x02", content_type)
