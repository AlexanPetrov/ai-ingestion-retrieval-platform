"""Dependency-free byte-level content checks for parsed ingestion."""

from fastapi import HTTPException

from ai_ingestion_retrieval_platform.core.response_admission import (
    normalize_content_type,
)

ERROR_CONTENT_BYTES_MISMATCH = "Response body does not match declared Content-Type"

_TEXT_CONTROL_BYTES_ALLOWED = {9, 10, 12, 13}
_HTML_PREFIXES = (
    b"<!doctype html",
    b"<html",
    b"<head",
    b"<body",
    b"<title",
    b"<meta",
)


def _strip_leading_text_whitespace(content: bytes) -> bytes:
    return content.lstrip(b"\xef\xbb\xbf\t\n\r\f ")


def _looks_like_pdf(content: bytes) -> bool:
    return _strip_leading_text_whitespace(content).startswith(b"%PDF-")


def _looks_like_html(content: bytes) -> bool:
    candidate = _strip_leading_text_whitespace(content).lower()

    if any(candidate.startswith(prefix) for prefix in _HTML_PREFIXES):
        return True

    return b"<html" in candidate[:512]


def _looks_like_text(content: bytes) -> bool:
    if not content:
        return True

    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False

    for byte in content:
        if byte < 32 and byte not in _TEXT_CONTROL_BYTES_ALLOWED:
            return False

    return True


def validate_content_matches_declared_type(
    content: bytes,
    content_type: str | None,
) -> None:
    """Reject content whose bytes clearly contradict the declared media type."""
    normalized_content_type = normalize_content_type(content_type)

    if normalized_content_type == "application/pdf":
        valid = _looks_like_pdf(content)
    elif normalized_content_type == "text/html":
        valid = _looks_like_html(content)
    elif normalized_content_type == "text/plain":
        valid = _looks_like_text(content)
    else:
        return

    if not valid:
        raise HTTPException(
            status_code=415,
            detail=ERROR_CONTENT_BYTES_MISMATCH,
        )
