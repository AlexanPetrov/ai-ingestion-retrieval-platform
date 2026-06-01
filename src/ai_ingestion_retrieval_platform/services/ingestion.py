import asyncio
from time import perf_counter

import httpx
import structlog
from fastapi import HTTPException
from pydantic import AnyHttpUrl
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ai_ingestion_retrieval_platform.core.config import get_settings
from ai_ingestion_retrieval_platform.core.http_client import get_http_client
from ai_ingestion_retrieval_platform.core.metrics import (
    INGESTION_BATCH_DURATION_SECONDS,
    INGESTION_BATCH_PREVIEW_TOTAL,
    INGESTION_URL_PREVIEW_TOTAL,
)
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionBatchResult,
    UrlIngestionError,
    UrlIngestionPreview,
)

logger = structlog.get_logger()
settings = get_settings()

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ReadTimeout):
        return False

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.NetworkError)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES

    return False


def build_ingestion_error(exc: HTTPException) -> UrlIngestionError:
    if exc.status_code == 504:
        return UrlIngestionError(
            code="timeout",
            message=str(exc.detail),
            status_code=exc.status_code,
        )

    if exc.status_code == 502:
        detail = str(exc.detail)

        if "HTTP" in detail:
            return UrlIngestionError(
                code="http_status",
                message=detail,
                status_code=exc.status_code,
            )

        return UrlIngestionError(
            code="network_error",
            message=detail,
            status_code=exc.status_code,
        )

    return UrlIngestionError(
        code="unknown_error",
        message=str(exc.detail),
        status_code=exc.status_code,
    )


@retry(
    retry=retry_if_exception(is_retryable_exception),
    stop=stop_after_attempt(settings.retry_attempts),
    wait=wait_exponential_jitter(
        initial=settings.retry_backoff_initial_seconds,
        max=settings.retry_backoff_max_seconds,
    ),
    reraise=True,
)
async def fetch_url(client: httpx.AsyncClient, url: str) -> httpx.Response:
    response = await client.get(url)
    response.raise_for_status()
    return response


async def preview_url(url: AnyHttpUrl) -> UrlIngestionPreview:
    start = perf_counter()
    url_str = str(url)

    logger.info("url_preview_started", url=url_str)

    try:
        client = get_http_client()
        response = await fetch_url(client, url_str)

    except httpx.TimeoutException as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        logger.warning(
            "url_preview_failed",
            url=url_str,
            error_type="timeout",
            elapsed_ms=elapsed_ms,
        )
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        raise HTTPException(
            status_code=504,
            detail="URL fetch timed out",
        ) from exc

    except httpx.HTTPStatusError as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        upstream_status_code = exc.response.status_code

        logger.warning(
            "url_preview_failed",
            url=url_str,
            error_type="http_status",
            upstream_status_code=upstream_status_code,
            elapsed_ms=elapsed_ms,
        )
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        raise HTTPException(
            status_code=502,
            detail=f"URL returned HTTP {upstream_status_code}",
        ) from exc

    except httpx.HTTPError as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        logger.warning(
            "url_preview_failed",
            url=url_str,
            error_type="network_error",
            elapsed_ms=elapsed_ms,
        )
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        raise HTTPException(
            status_code=502,
            detail="URL fetch failed",
        ) from exc

    elapsed_ms = round((perf_counter() - start) * 1000, 2)

    logger.info(
        "url_preview_completed",
        url=url_str,
        status_code=response.status_code,
        content_length=len(response.content),
        elapsed_ms=elapsed_ms,
    )

    INGESTION_URL_PREVIEW_TOTAL.labels(result="success").inc()

    return UrlIngestionPreview(
        url=url_str,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=len(response.content),
        elapsed_ms=elapsed_ms,
        preview=response.text[:500],
    )


async def preview_urls(
    urls: list[AnyHttpUrl],
    max_concurrency: int,
) -> list[UrlIngestionBatchResult]:
    logger.info(
        "batch_preview_started",
        url_count=len(urls),
        max_concurrency=max_concurrency,
    )

    start = perf_counter()
    semaphore = asyncio.Semaphore(max_concurrency)

    async def preview_with_limit(url: AnyHttpUrl) -> UrlIngestionBatchResult:
        async with semaphore:
            try:
                preview = await preview_url(url)
                return UrlIngestionBatchResult(
                    url=str(url),
                    success=True,
                    data=preview,
                    error=None,
                )
            except HTTPException as exc:
                return UrlIngestionBatchResult(
                    url=str(url),
                    success=False,
                    data=None,
                    error=build_ingestion_error(exc),
                )

    results = await asyncio.gather(*(preview_with_limit(url) for url in urls))

    elapsed_seconds = perf_counter() - start
    elapsed_ms = round(elapsed_seconds * 1000, 2)
    success_count = sum(1 for result in results if result.success)
    failure_count = len(results) - success_count

    if failure_count:
        INGESTION_BATCH_PREVIEW_TOTAL.labels(result="partial_failure").inc()
    else:
        INGESTION_BATCH_PREVIEW_TOTAL.labels(result="success").inc()

    INGESTION_BATCH_DURATION_SECONDS.observe(elapsed_seconds)

    logger.info(
        "batch_preview_completed",
        url_count=len(urls),
        success_count=success_count,
        failure_count=failure_count,
        elapsed_ms=elapsed_ms,
    )

    return results
