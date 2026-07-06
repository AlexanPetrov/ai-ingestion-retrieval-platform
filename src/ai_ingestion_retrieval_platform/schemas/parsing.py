"""Typed parser boundary schemas."""

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    content: bytes = Field(description="Raw document bytes to parse.")
    content_type: str = Field(
        description="Response content type used for parser choice."
    )
    source_url: str | None = Field(
        default=None,
        description="Optional source URL for parser metadata.",
    )


class ParsedDocument(BaseModel):
    text: str
    content_type: str
    source_url: str | None = None
    byte_length: int
    char_length: int
