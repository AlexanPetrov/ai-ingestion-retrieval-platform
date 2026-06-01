from pydantic import AnyHttpUrl, BaseModel, Field


class UrlIngestionRequest(BaseModel):
    url: AnyHttpUrl = Field(
        examples=["https://example.com"],
        description="Public URL to fetch for ingestion.",
    )


class BatchUrlIngestionRequest(BaseModel):
    urls: list[AnyHttpUrl] = Field(
        min_length=1,
        max_length=20,
        examples=[["https://example.com", "https://httpbin.org/html"]],
        description="Public URLs to fetch for ingestion preview.",
    )
    max_concurrency: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of URLs fetched at the same time.",
    )


class UrlIngestionPreview(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float
    preview: str


class UrlIngestionBatchResult(BaseModel):
    url: str
    success: bool
    data: UrlIngestionPreview | None
    error: str | None