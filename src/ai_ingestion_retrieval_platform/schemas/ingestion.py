"""Pydantic schemas for ingestion preview requests and responses."""

from pydantic import AnyHttpUrl, BaseModel, Field


class UrlIngestionRequest(BaseModel):
    url: AnyHttpUrl = Field(
        examples=["https://example.com"],
        description="Public URL to fetch for ingestion.",
    )


class BatchUrlIngestionRequest(BaseModel):
    urls: list[AnyHttpUrl] = Field(
        min_length=1,
        examples=[["https://example.com", "https://httpbin.org/html"]],
        description="Public URLs to fetch for ingestion preview.",
    )
    max_concurrency: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Maximum number of URLs fetched at the same time. "
            "Uses the application default when omitted."
        ),
    )


class UrlIngestionPreview(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float
    preview: str


class UrlParsedIngestionPreview(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float
    parsed_content_type: str
    parsed_char_length: int
    parsed_preview: str


class UrlIngestionError(BaseModel):
    code: str
    message: str
    status_code: int | None = None


class UrlIngestionBatchResult(BaseModel):
    url: str
    success: bool
    data: UrlIngestionPreview | None
    error: UrlIngestionError | None


class UrlParsedIngestionBatchResult(BaseModel):
    url: str
    success: bool
    data: UrlParsedIngestionPreview | None
    error: UrlIngestionError | None
