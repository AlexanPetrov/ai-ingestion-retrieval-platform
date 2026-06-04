from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from ai_ingestion_retrieval_platform.api.dependencies.http_client import get_http_client
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    BatchUrlIngestionRequest,
    UrlIngestionBatchResult,
    UrlIngestionPreview,
    UrlIngestionRequest,
)
from ai_ingestion_retrieval_platform.services.ingestion import preview_url, preview_urls

router = APIRouter()
HttpClientDependency = Annotated[httpx.AsyncClient, Depends(get_http_client)]


@router.post("/url/preview", response_model=UrlIngestionPreview)
async def preview_url_ingestion(
    request: UrlIngestionRequest,
    http_client: HttpClientDependency,
) -> UrlIngestionPreview:
    return await preview_url(request.url, http_client)


@router.post("/urls/preview", response_model=list[UrlIngestionBatchResult])
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_client: HttpClientDependency,
) -> list[UrlIngestionBatchResult]:
    return await preview_urls(
        urls=request.urls,
        max_concurrency=request.max_concurrency,
        client=http_client,
    )
