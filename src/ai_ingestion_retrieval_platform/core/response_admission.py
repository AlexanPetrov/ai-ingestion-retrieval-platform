"""Response-header admission checks for outbound ingestion fetches."""

from collections.abc import Collection

from fastapi import HTTPException

ERROR_DECLARED_CONTENT_TOO_LARGE = (
    "Response Content-Length exceeds the allowed byte limit"
)
ERROR_CONTENT_TYPE_MISSING = "Response Content-Type header is required"
ERROR_CONTENT_TYPE_UNSUPPORTED = "Response Content-Type is not supported"


def normalize_content_type(content_type: str | None) -> str | None:
    """Return a lowercase media type without parameters."""
    if content_type is None:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized or None


def parse_content_length(content_length: str | None) -> int | None:
    """Return a valid non-negative Content-Length value when available."""
    if content_length is None:
        return None

    try:
        parsed_length = int(content_length.strip())
    except ValueError:
        return None

    if parsed_length < 0:
        return None

    return parsed_length


def validate_declared_content_length(
    content_length: str | None,
    max_bytes: int,
) -> int | None:
    """Reject a response whose declared size exceeds the byte limit."""
    declared_length = parse_content_length(content_length)

    if declared_length is not None and declared_length > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=ERROR_DECLARED_CONTENT_TOO_LARGE,
        )

    return declared_length


def validate_allowed_content_type(
    content_type: str | None,
    allowed_content_types: Collection[str],
) -> str:
    """Return the normalized type when it is present and allowed."""
    normalized_content_type = normalize_content_type(content_type)

    if normalized_content_type is None:
        raise HTTPException(
            status_code=415,
            detail=ERROR_CONTENT_TYPE_MISSING,
        )

    normalized_allowed_types = {
        normalized
        for allowed_type in allowed_content_types
        if (normalized := normalize_content_type(allowed_type)) is not None
    }

    if normalized_content_type not in normalized_allowed_types:
        raise HTTPException(
            status_code=415,
            detail=ERROR_CONTENT_TYPE_UNSUPPORTED,
        )

    return normalized_content_type
