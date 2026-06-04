from pydantic import AnyHttpUrl, BaseModel, Field

from ai_ingestion_retrieval_platform.core.config import get_settings

settings = get_settings()


class UrlIngestionRequest(BaseModel):
    url: AnyHttpUrl = Field(
        examples=["https://example.com"],
        description="Public URL to fetch for ingestion.",
    )


class BatchUrlIngestionRequest(BaseModel):
    urls: list[AnyHttpUrl] = Field(
        min_length=1,
        max_length=settings.max_batch_urls,
        examples=[["https://example.com", "https://httpbin.org/html"]],
        description="Public URLs to fetch for ingestion preview.",
    )
    max_concurrency: int = Field(
        default=settings.default_max_concurrency,
        ge=1,
        le=settings.max_allowed_concurrency,
        description="Maximum number of URLs fetched at the same time.",
    )


class UrlIngestionPreview(BaseModel):
    url: str
    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float
    preview: str


class UrlIngestionError(BaseModel):
    code: str
    message: str
    status_code: int | None = None


class UrlIngestionBatchResult(BaseModel):
    url: str
    success: bool
    data: UrlIngestionPreview | None
    error: UrlIngestionError | None
