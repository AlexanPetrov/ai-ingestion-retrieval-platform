"""Ingestion API routes for URL preview and persistent ingestion requests."""

import asyncio
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AnyHttpUrl

from ai_ingestion_retrieval_platform.api.dependencies.auth import (
    require_ingestion_auth,
)
from ai_ingestion_retrieval_platform.api.dependencies.database import (
    DatabaseSessionDependency,
    DatabaseSessionFactoryDependency,
)
from ai_ingestion_retrieval_platform.api.dependencies.http_client import (
    get_http_client,
)
from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    enforce_batch_preview_rate_limit,
    enforce_url_preview_rate_limit,
)
from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.limits import create_batch_limiter
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    BatchUrlIngestionRequest,
    UrlIngestionBatchResult,
    UrlIngestionPreview,
    UrlIngestionRequest,
    UrlParsedIngestionBatchResult,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.schemas.persistence import (
    BatchIngestResponse,
    BatchParsedIngestResponse,
    UrlIngestedBatchResult,
    UrlIngestedPreview,
    UrlParsedIngestedBatchResult,
    UrlParsedIngestedPreview,
)
from ai_ingestion_retrieval_platform.services.ingestion import (
    build_ingestion_error,
    preview_parsed_url,
    preview_parsed_urls,
    preview_url,
    preview_urls,
)
from ai_ingestion_retrieval_platform.services.persistence import (
    ingest_parsed_url,
    ingest_url,
)

router = APIRouter(
    dependencies=[
        Depends(require_ingestion_auth),
    ]
)

HttpClientDependency = Annotated[
    httpx.AsyncClient,
    Depends(get_http_client),
]

AppSettingsDependency = Annotated[
    Settings,
    Depends(get_app_settings),
]


def _get_client_ip(request: Request) -> str | None:
    """Return the directly connected client IP address.

    Trusted proxy forwarding is intentionally not handled here yet.
    """
    if request.client is None:
        return None

    return request.client.host


def _get_request_id(request: Request) -> str | None:
    """Return the request correlation ID created or propagated by middleware."""
    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    if isinstance(request_id, str):
        return request_id

    return None


def _resolve_batch_max_concurrency(
    request: BatchUrlIngestionRequest,
    settings: Settings,
) -> int:
    """Validate app-scoped batch limits and resolve default concurrency."""
    if len(request.urls) > settings.max_batch_urls:
        raise HTTPException(
            status_code=422,
            detail=(f"Batch cannot contain more than {settings.max_batch_urls} URLs"),
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


# ---------------------------------------------------------------------------
# Preview routes
# ---------------------------------------------------------------------------


@router.post(
    "/url/preview",
    response_model=UrlIngestionPreview,
)
async def preview_url_ingestion(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> UrlIngestionPreview:
    """Fetch one URL and return a raw preview without persistence."""
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


@router.post(
    "/url/parse-preview",
    response_model=UrlParsedIngestionPreview,
)
async def preview_parsed_url_ingestion(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> UrlParsedIngestionPreview:
    """Fetch and parse one URL without persistence."""
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


@router.post(
    "/urls/preview",
    response_model=list[UrlIngestionBatchResult],
)
async def preview_urls_ingestion(
    request: BatchUrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    app_settings: AppSettingsDependency,
) -> list[UrlIngestionBatchResult]:
    """Fetch multiple URLs and return raw previews without persistence."""
    max_concurrency = _resolve_batch_max_concurrency(
        request,
        app_settings,
    )

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
    """Fetch and parse multiple URLs without persistence."""
    max_concurrency = _resolve_batch_max_concurrency(
        request,
        app_settings,
    )

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


# ---------------------------------------------------------------------------
# Persistent ingestion routes
# ---------------------------------------------------------------------------


@router.post(
    "/url/ingest",
    response_model=UrlIngestedPreview,
)
async def ingest_url_route(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    session: DatabaseSessionDependency,
    app_settings: AppSettingsDependency,
) -> UrlIngestedPreview:
    """Fetch one URL, return a raw preview, and persist the ingestion."""
    await _enforce_single_url_rate_limit(
        request=http_request,
        settings=app_settings,
        parsed_preview=False,
    )

    request_id = _get_request_id(http_request)
    client_ip = _get_client_ip(http_request)

    ingestion_record_id, source_id, preview = await ingest_url(
        request.url,
        http_client,
        session,
        app_settings=app_settings,
        request_id=request_id,
        client_ip=client_ip,
    )

    return UrlIngestedPreview(
        url=preview.url,
        ingestion_record_id=ingestion_record_id,
        source_id=source_id,
        status_code=preview.status_code,
        content_type=preview.content_type,
        content_length=preview.content_length,
        elapsed_ms=preview.elapsed_ms,
        preview=preview.preview,
    )


@router.post(
    "/url/parse-ingest",
    response_model=UrlParsedIngestedPreview,
)
async def ingest_parsed_url_route(
    request: UrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    session: DatabaseSessionDependency,
    app_settings: AppSettingsDependency,
) -> UrlParsedIngestedPreview:
    """Fetch, parse, and persist one URL."""
    await _enforce_single_url_rate_limit(
        request=http_request,
        settings=app_settings,
        parsed_preview=True,
    )

    request_id = _get_request_id(http_request)
    client_ip = _get_client_ip(http_request)

    (
        ingestion_record_id,
        source_id,
        parsed_document_id,
        preview,
    ) = await ingest_parsed_url(
        request.url,
        http_client,
        session,
        app_settings=app_settings,
        request_id=request_id,
        client_ip=client_ip,
    )

    return UrlParsedIngestedPreview(
        url=preview.url,
        ingestion_record_id=ingestion_record_id,
        source_id=source_id,
        parsed_document_id=parsed_document_id,
        status_code=preview.status_code,
        content_type=preview.content_type,
        content_length=preview.content_length,
        elapsed_ms=preview.elapsed_ms,
        parsed_content_type=preview.parsed_content_type,
        parsed_char_length=preview.parsed_char_length,
        parsed_preview=preview.parsed_preview,
    )


@router.post(
    "/urls/ingest",
    response_model=BatchIngestResponse,
)
async def ingest_urls_route(
    request: BatchUrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    session_factory: DatabaseSessionFactoryDependency,
    app_settings: AppSettingsDependency,
) -> BatchIngestResponse:
    """Fetch and persist multiple URLs with isolated database sessions."""
    max_concurrency = _resolve_batch_max_concurrency(
        request,
        app_settings,
    )

    await _enforce_batch_rate_limit(
        request=http_request,
        payload=request,
        settings=app_settings,
        parsed_preview=False,
    )

    batch_id = uuid4()
    request_id = _get_request_id(http_request)
    client_ip = _get_client_ip(http_request)
    batch_limiter = create_batch_limiter(max_concurrency)

    async def ingest_single_url(
        batch_position: int,
        url: AnyHttpUrl,
    ) -> UrlIngestedBatchResult:
        async with batch_limiter:
            # Concurrent tasks must never share one AsyncSession.
            async with session_factory() as session:
                try:
                    (
                        ingestion_record_id,
                        source_id,
                        preview,
                    ) = await ingest_url(
                        url,
                        http_client,
                        session,
                        app_settings=app_settings,
                        request_id=request_id,
                        client_ip=client_ip,
                        batch_id=batch_id,
                        batch_position=batch_position,
                    )

                    return UrlIngestedBatchResult(
                        url=preview.url,
                        success=True,
                        data=UrlIngestedPreview(
                            url=preview.url,
                            ingestion_record_id=ingestion_record_id,
                            source_id=source_id,
                            status_code=preview.status_code,
                            content_type=preview.content_type,
                            content_length=preview.content_length,
                            elapsed_ms=preview.elapsed_ms,
                            preview=preview.preview,
                        ),
                        error=None,
                    )

                except HTTPException as exc:
                    return UrlIngestedBatchResult(
                        url=str(url),
                        success=False,
                        data=None,
                        error=build_ingestion_error(exc),
                    )

    results = await asyncio.gather(
        *[
            ingest_single_url(
                batch_position,
                url,
            )
            for batch_position, url in enumerate(request.urls)
        ],
        return_exceptions=False,
    )

    return BatchIngestResponse(
        batch_id=batch_id,
        results=results,
    )


@router.post(
    "/urls/parse-ingest",
    response_model=BatchParsedIngestResponse,
)
async def ingest_parsed_urls_route(
    request: BatchUrlIngestionRequest,
    http_request: Request,
    http_client: HttpClientDependency,
    session_factory: DatabaseSessionFactoryDependency,
    app_settings: AppSettingsDependency,
) -> BatchParsedIngestResponse:
    """Fetch, parse, and persist multiple URLs with isolated DB sessions."""
    max_concurrency = _resolve_batch_max_concurrency(
        request,
        app_settings,
    )

    await _enforce_batch_rate_limit(
        request=http_request,
        payload=request,
        settings=app_settings,
        parsed_preview=True,
    )

    batch_id = uuid4()
    request_id = _get_request_id(http_request)
    client_ip = _get_client_ip(http_request)
    batch_limiter = create_batch_limiter(max_concurrency)

    async def ingest_single_parsed_url(
        batch_position: int,
        url: AnyHttpUrl,
    ) -> UrlParsedIngestedBatchResult:
        async with batch_limiter:
            # One AsyncSession belongs to exactly one concurrent task.
            async with session_factory() as session:
                try:
                    (
                        ingestion_record_id,
                        source_id,
                        parsed_document_id,
                        preview,
                    ) = await ingest_parsed_url(
                        url,
                        http_client,
                        session,
                        app_settings=app_settings,
                        request_id=request_id,
                        client_ip=client_ip,
                        batch_id=batch_id,
                        batch_position=batch_position,
                    )

                    return UrlParsedIngestedBatchResult(
                        url=preview.url,
                        success=True,
                        data=UrlParsedIngestedPreview(
                            url=preview.url,
                            ingestion_record_id=ingestion_record_id,
                            source_id=source_id,
                            parsed_document_id=parsed_document_id,
                            status_code=preview.status_code,
                            content_type=preview.content_type,
                            content_length=preview.content_length,
                            elapsed_ms=preview.elapsed_ms,
                            parsed_content_type=preview.parsed_content_type,
                            parsed_char_length=preview.parsed_char_length,
                            parsed_preview=preview.parsed_preview,
                        ),
                        error=None,
                    )

                except HTTPException as exc:
                    return UrlParsedIngestedBatchResult(
                        url=str(url),
                        success=False,
                        data=None,
                        error=build_ingestion_error(exc),
                    )

    results = await asyncio.gather(
        *[
            ingest_single_parsed_url(
                batch_position,
                url,
            )
            for batch_position, url in enumerate(request.urls)
        ],
        return_exceptions=False,
    )

    return BatchParsedIngestResponse(
        batch_id=batch_id,
        results=results,
    )
