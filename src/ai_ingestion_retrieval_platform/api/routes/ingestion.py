"""Ingestion API routes for URL preview requests."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ai_ingestion_retrieval_platform.api.dependencies.http_client import get_http_client
from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    rate_limit_batch_preview,
    rate_limit_url_preview,
)
from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)
from ai_ingestion_retrieval_platform.core.config import Settings
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
AppSettingsDependency = Annotated[Settings, Depends(get_app_settings)]
UrlPreviewRateLimit = Annotated[None, Depends(rate_limit_url_preview)]
BatchPreviewRateLimit = Annotated[None, Depends(rate_limit_batch_preview)]


def _resolve_batch_max_concurrency(
    request: BatchUrlIngestionRequest,
    settings: Settings,
) -> int:
    """Validate app-scoped batch limits and resolve default concurrency."""
    if len(request.urls) > settings.max_batch_urls:
        raise HTTPException(
            status_code=422,
            detail=f"Batch cannot contain more than {settings.max_batch_urls} URLs",
        )

    max_concurrency = (
        settings.default_max_concurrency
        if request.max_concurrency is None
        else request.max_concurrency
    )

    if max_concurrency > settings.max_allowed_concurrency:
        raise HTTPException(
            status_code=422,
            detail=(
                f"max_concurrency cannot exceed {settings.max_allowed_concurrency}"
            ),
        )

    return max_concurrency


@router.post("/url/preview", response_model=UrlIngestionPreview)
async def preview_url_ingestion(
    request: UrlIngestionRequest,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
    _rate_limit: UrlPreviewRateLimit,
) -> UrlIngestionPreview:
    return await preview_url(
        request.url,
        http_client,
        app_settings=app_settings,
    )


@router.post("/url/parse-preview", response_model=UrlParsedIngestionPreview)
async def preview_parsed_url_ingestion(
    request: UrlIngestionRequest,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
    _rate_limit: UrlPreviewRateLimit,
) -> UrlParsedIngestionPreview:
    return await preview_parsed_url(
        request.url,
        http_client,
        app_settings=app_settings,
    )


@router.post("/urls/preview", response_model=list[UrlIngestionBatchResult])
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
    _rate_limit: BatchPreviewRateLimit,
) -> list[UrlIngestionBatchResult]:
    max_concurrency = _resolve_batch_max_concurrency(request, app_settings)

    return await preview_urls(
        urls=request.urls,
        max_concurrency=max_concurrency,
        client=http_client,
        app_settings=app_settings,
    )


@router.post(
    "/urls/parse-preview",
    response_model=list[UrlParsedIngestionBatchResult],
)
async def preview_parsed_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
    _rate_limit: BatchPreviewRateLimit,
) -> list[UrlParsedIngestionBatchResult]:
    max_concurrency = _resolve_batch_max_concurrency(request, app_settings)

    return await preview_parsed_urls(
        urls=request.urls,
        max_concurrency=max_concurrency,
        client=http_client,
        app_settings=app_settings,
    )
