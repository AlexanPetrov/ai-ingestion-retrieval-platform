"""Content identity helpers."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256


class ContentIdentityState(StrEnum):
    """Relationship between current and previously persisted parsed content."""

    NEW = "new"
    UNCHANGED = "unchanged"
    CHANGED = "changed"


def calculate_content_sha256(text: str) -> str:
    """Return the SHA-256 digest for the exact UTF-8 encoded text.

    The input is hashed exactly as provided. No whitespace, Unicode,
    newline, case, or other normalization is performed.
    """
    return sha256(text.encode("utf-8")).hexdigest()


def classify_content_identity(
    *,
    current_sha256: str,
    previous_sha256: str | None,
) -> ContentIdentityState:
    """Classify current parsed content against the previous successful parse.

    A missing previous digest means this is the first known successfully parsed
    content for the source. Equal digests mean the parsed content is unchanged.
    Different digests mean the parsed content has changed.
    """
    if previous_sha256 is None:
        return ContentIdentityState.NEW

    if current_sha256 == previous_sha256:
        return ContentIdentityState.UNCHANGED

    return ContentIdentityState.CHANGED
