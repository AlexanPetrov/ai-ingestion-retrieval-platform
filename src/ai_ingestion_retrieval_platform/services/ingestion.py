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
from ai_ingestion_retrieval_platform.core.limits import outbound_fetch_limiter
from ai_ingestion_retrieval_platform.core.metrics import (
    INGESTION_BATCH_DURATION_SECONDS,
    INGESTION_BATCH_PREVIEW_TOTAL,
    INGESTION_URL_PREVIEW_TOTAL,
)
from ai_ingestion_retrieval_platform.core.url_safety import validate_url_is_safe
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionBatchResult,
    UrlIngestionError,
    UrlIngestionPreview,
)

logger = structlog.get_logger()
settings = get_settings()

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

ERROR_TOO_MANY_REDIRECTS = "Too many redirects"
ERROR_REDIRECT_MISSING_LOCATION = "Redirect response missing Location header"
ERROR_TIMEOUT = "URL fetch timed out"
ERROR_FETCH_FAILED = "URL fetch failed"


def is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ReadTimeout):
        return False

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.NetworkError)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES

    return False


def build_ingestion_error(exc: HTTPException) -> UrlIngestionError:
    detail = str(exc.detail)

    if detail == ERROR_TOO_MANY_REDIRECTS:
        return UrlIngestionError(
            code="too_many_redirects",
            message=detail,
            status_code=exc.status_code,
        )

    if detail == ERROR_REDIRECT_MISSING_LOCATION:
        return UrlIngestionError(
            code="redirect_error",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 400:
        return UrlIngestionError(
            code="unsafe_url",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 504:
        return UrlIngestionError(
            code="timeout",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 502:
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
        message=detail,
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
    async with outbound_fetch_limiter:
        current_url = url

        for _ in range(settings.max_redirects + 1):
            await validate_url_is_safe(current_url)

            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    redirect_url = response.headers.get("location")

                    if not redirect_url:
                        raise HTTPException(
                            status_code=400,
                            detail=ERROR_REDIRECT_MISSING_LOCATION,
                        )

                    current_url = str(response.url.join(redirect_url))
                    continue

                response.raise_for_status()

                body = bytearray()

                async for chunk in response.aiter_bytes():
                    remaining = settings.max_preview_bytes - len(body)

                    if remaining <= 0:
                        break

                    body.extend(chunk[:remaining])

                response._content = bytes(body)
                return response

        raise HTTPException(
            status_code=400,
            detail=ERROR_TOO_MANY_REDIRECTS,
        )


async def preview_url(url: AnyHttpUrl) -> UrlIngestionPreview:
    start = perf_counter()
    url_str = str(url)

    logger.info("url_preview_started", url=url_str)

    try:
        client = get_http_client()
        response = await fetch_url(client, url_str)

    except HTTPException:
        raise

    except httpx.TimeoutException as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)

        logger.warning(
            "url_preview_failed",
            url=url_str,
            error_type="timeout",
            elapsed_ms=elapsed_ms,
        )

        raise HTTPException(
            status_code=504,
            detail=ERROR_TIMEOUT,
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

        raise HTTPException(
            status_code=502,
            detail=ERROR_FETCH_FAILED,
        ) from exc

    elapsed_ms = round((perf_counter() - start) * 1000, 2)

    logger.info(
        "url_preview_completed",
        url=url_str,
        status_code=response.status_code,
        content_length=len(response.content),
        elapsed_ms=elapsed_ms,
    )

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

                INGESTION_URL_PREVIEW_TOTAL.labels(result="success").inc()

                return UrlIngestionBatchResult(
                    url=str(url),
                    success=True,
                    data=preview,
                    error=None,
                )

            except HTTPException as exc:
                INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()

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
