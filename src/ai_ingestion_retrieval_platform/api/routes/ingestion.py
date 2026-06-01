from fastapi import APIRouter

from ai_ingestion_retrieval_platform.schemas.ingestion import (
    BatchUrlIngestionRequest,
    UrlIngestionBatchResult,
    UrlIngestionPreview,
    UrlIngestionRequest,
)
from ai_ingestion_retrieval_platform.services.ingestion import preview_url, preview_urls

router = APIRouter()


@router.post("/url/preview", response_model=UrlIngestionPreview)
async def preview_url_ingestion(request: UrlIngestionRequest) -> UrlIngestionPreview:
    return await preview_url(request.url)


@router.post("/urls/preview", response_model=list[UrlIngestionBatchResult])
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
) -> list[UrlIngestionBatchResult]:
    return await preview_urls(
        urls=request.urls,
        max_concurrency=request.max_concurrency,
    )