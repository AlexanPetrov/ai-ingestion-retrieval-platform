"""Ingestion API routes for URL preview requests."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from ai_ingestion_retrieval_platform.api.dependencies.http_client import get_http_client
from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    rate_limit_batch_preview,
    rate_limit_url_preview,
)
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    BatchUrlIngestionRequest,
    UrlIngestionBatchResult,
    UrlIngestionPreview,
    UrlIngestionRequest,
    UrlParsedIngestionBatchResult,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.services.ingestion import (
    preview_parsed_url,
    preview_parsed_urls,
    preview_url,
    preview_urls,
)

router = APIRouter()
HttpClientDependency = Annotated[httpx.AsyncClient, Depends(get_http_client)]
UrlPreviewRateLimit = Annotated[None, Depends(rate_limit_url_preview)]
BatchPreviewRateLimit = Annotated[None, Depends(rate_limit_batch_preview)]


@router.post("/url/preview", response_model=UrlIngestionPreview)
async def preview_url_ingestion(
    request: UrlIngestionRequest,
    http_client: HttpClientDependency,
    _rate_limit: UrlPreviewRateLimit,
) -> UrlIngestionPreview:
    return await preview_url(request.url, http_client)


@router.post("/url/parse-preview", response_model=UrlParsedIngestionPreview)
async def preview_parsed_url_ingestion(
    request: UrlIngestionRequest,
    http_client: HttpClientDependency,
    _rate_limit: UrlPreviewRateLimit,
) -> UrlParsedIngestionPreview:
    return await preview_parsed_url(request.url, http_client)


@router.post("/urls/preview", response_model=list[UrlIngestionBatchResult])
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_client: HttpClientDependency,
    _rate_limit: BatchPreviewRateLimit,
) -> list[UrlIngestionBatchResult]:
    return await preview_urls(
        urls=request.urls,
        max_concurrency=request.max_concurrency,
        client=http_client,
    )


@router.post(
    "/urls/parse-preview",
    response_model=list[UrlParsedIngestionBatchResult],
)
async def preview_parsed_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_client: HttpClientDependency,
    _rate_limit: BatchPreviewRateLimit,
) -> list[UrlParsedIngestionBatchResult]:
    return await preview_parsed_urls(
        urls=request.urls,
        max_concurrency=request.max_concurrency,
        client=http_client,
    )
