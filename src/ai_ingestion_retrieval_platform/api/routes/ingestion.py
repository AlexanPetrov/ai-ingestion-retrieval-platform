"""Ingestion API routes for URL preview requests."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ai_ingestion_retrieval_platform.api.dependencies.auth import (
    require_ingestion_auth,
)
from ai_ingestion_retrieval_platform.api.dependencies.http_client import get_http_client
from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    enforce_batch_preview_rate_limit,
    enforce_url_preview_rate_limit,
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

router = APIRouter(dependencies=[Depends(require_ingestion_auth)])

HttpClientDependency = Annotated[httpx.AsyncClient, Depends(get_http_client)]
AppSettingsDependency = Annotated[Settings, Depends(get_app_settings)]


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


async def _enforce_single_url_rate_limit(
    request: Request,
    settings: Settings,
    *,
    parsed_preview: bool,
) -> None:
    """Apply weighted rate limiting for single-URL ingestion routes."""
    cost = (
        settings.rate_limit_url_parse_preview_cost
        if parsed_preview
        else settings.rate_limit_url_preview_cost
    )

    await enforce_url_preview_rate_limit(
        request=request,
        cost=cost,
    )


async def _enforce_batch_rate_limit(
    request: Request,
    payload: BatchUrlIngestionRequest,
    settings: Settings,
    *,
    parsed_preview: bool,
) -> None:
    """Apply weighted rate limiting for batch ingestion routes."""
    per_url_cost = (
        settings.rate_limit_batch_parse_preview_url_cost
        if parsed_preview
        else settings.rate_limit_batch_preview_url_cost
    )

    await enforce_batch_preview_rate_limit(
        request=request,
        cost=len(payload.urls) * per_url_cost,
    )


@router.post("/url/preview", response_model=UrlIngestionPreview)
async def preview_url_ingestion(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> UrlIngestionPreview:
    await _enforce_single_url_rate_limit(
        request=http_request,
        settings=app_settings,
        parsed_preview=False,
    )

    return await preview_url(
        request.url,
        http_client,
        app_settings=app_settings,
    )


@router.post("/url/parse-preview", response_model=UrlParsedIngestionPreview)
async def preview_parsed_url_ingestion(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> UrlParsedIngestionPreview:
    await _enforce_single_url_rate_limit(
        request=http_request,
        settings=app_settings,
        parsed_preview=True,
    )

    return await preview_parsed_url(
        request.url,
        http_client,
        app_settings=app_settings,
    )


@router.post("/urls/preview", response_model=list[UrlIngestionBatchResult])
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> list[UrlIngestionBatchResult]:
    max_concurrency = _resolve_batch_max_concurrency(request, app_settings)

    await _enforce_batch_rate_limit(
        request=http_request,
        payload=request,
        settings=app_settings,
        parsed_preview=False,
    )

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
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> list[UrlParsedIngestionBatchResult]:
    max_concurrency = _resolve_batch_max_concurrency(request, app_settings)

    await _enforce_batch_rate_limit(
        request=http_request,
        payload=request,
        settings=app_settings,
        parsed_preview=True,
    )

    return await preview_parsed_urls(
        urls=request.urls,
        max_concurrency=max_concurrency,
        client=http_client,
        app_settings=app_settings,
    )
