"""URL ingestion service orchestration, parsing, and batch handling."""

import asyncio
from time import perf_counter

import httpx
import structlog
from fastapi import HTTPException
from pydantic import AnyHttpUrl

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.limits import create_batch_limiter
from ai_ingestion_retrieval_platform.core.metrics import (
    INGESTION_BATCH_DURATION_SECONDS,
    INGESTION_BATCH_IN_FLIGHT,
    INGESTION_BATCH_LIMITER_WAIT_SECONDS,
    INGESTION_BATCH_PREVIEW_TOTAL,
    INGESTION_URL_PREVIEW_TOTAL,
    INGESTION_URL_TIMEOUT_TOTAL,
)
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionBatchResult,
    UrlIngestionError,
    UrlIngestionPreview,
    UrlParsedIngestionBatchResult,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParseRequest
from ai_ingestion_retrieval_platform.services.fetching import (
    ERROR_REDIRECT_MISSING_LOCATION,
    ERROR_TOO_MANY_REDIRECTS,
    fetch_url,
    resolve_settings,
)
from ai_ingestion_retrieval_platform.services.parsing import parse_document

logger = structlog.get_logger()

ERROR_TIMEOUT = "URL fetch timed out"
ERROR_FETCH_FAILED = "URL fetch failed"


def _resolve_settings(app_settings: Settings | None) -> Settings:
    """Return explicitly provided app settings or freshly loaded defaults."""
    return resolve_settings(app_settings)


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

    if detail == "Only http and https URLs are allowed":
        return UrlIngestionError(
            code="unsupported_url_scheme",
            message=detail,
            status_code=exc.status_code,
        )

    if detail == "URL credentials are not allowed":
        return UrlIngestionError(
            code="url_credentials_not_allowed",
            message=detail,
            status_code=exc.status_code,
        )

    if detail == "URL port is not allowed":
        return UrlIngestionError(
            code="url_port_not_allowed",
            message=detail,
            status_code=exc.status_code,
        )

    if detail == "URL port is invalid":
        return UrlIngestionError(
            code="url_port_invalid",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 400:
        return UrlIngestionError(
            code="unsafe_url",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 413:
        return UrlIngestionError(
            code="content_too_large",
            message=detail,
            status_code=exc.status_code,
        )

    if exc.status_code == 415:
        return UrlIngestionError(
            code="unsupported_content_type",
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


async def preview_url(
    url: AnyHttpUrl,
    client: httpx.AsyncClient,
    url_timeout: float | None = None,
    app_settings: Settings | None = None,
) -> UrlIngestionPreview:
    runtime_settings = _resolve_settings(app_settings)
    start = perf_counter()
    url_str = str(url)

    logger.info("url_preview_started", url=url_str)

    try:
        response = await fetch_url(
            client,
            url_str,
            url_timeout=url_timeout,
            app_settings=runtime_settings,
        )

    except HTTPException:
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        raise

    except TimeoutError as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        INGESTION_URL_TIMEOUT_TOTAL.labels(reason="asyncio_timeout").inc()

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

    except httpx.TimeoutException as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        INGESTION_URL_TIMEOUT_TOTAL.labels(reason=type(exc).__name__).inc()

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
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()

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
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()

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
    INGESTION_URL_PREVIEW_TOTAL.labels(result="success").inc()

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
        preview=response.text[: runtime_settings.max_preview_text_chars],
    )


async def preview_parsed_url(
    url: AnyHttpUrl,
    client: httpx.AsyncClient,
    url_timeout: float | None = None,
    app_settings: Settings | None = None,
) -> UrlParsedIngestionPreview:
    runtime_settings = _resolve_settings(app_settings)
    start = perf_counter()
    url_str = str(url)

    logger.info("url_parse_preview_started", url=url_str)

    try:
        response = await fetch_url(
            client,
            url_str,
            url_timeout=url_timeout,
            max_bytes=runtime_settings.max_parse_bytes,
            allowed_content_types=runtime_settings.allowed_parse_content_types,
            app_settings=runtime_settings,
        )

        parsed = await parse_document(
            ParseRequest(
                content=response.content,
                content_type=response.headers.get("content-type")
                or "application/octet-stream",
                source_url=url_str,
            ),
            settings=runtime_settings,
        )

    except HTTPException:
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        raise

    except TimeoutError as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        INGESTION_URL_TIMEOUT_TOTAL.labels(reason="asyncio_timeout").inc()

        logger.warning(
            "url_parse_preview_failed",
            url=url_str,
            error_type="timeout",
            elapsed_ms=elapsed_ms,
        )

        raise HTTPException(
            status_code=504,
            detail=ERROR_TIMEOUT,
        ) from exc

    except httpx.TimeoutException as exc:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()
        INGESTION_URL_TIMEOUT_TOTAL.labels(reason=type(exc).__name__).inc()

        logger.warning(
            "url_parse_preview_failed",
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
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()

        logger.warning(
            "url_parse_preview_failed",
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
        INGESTION_URL_PREVIEW_TOTAL.labels(result="failure").inc()

        logger.warning(
            "url_parse_preview_failed",
            url=url_str,
            error_type="network_error",
            elapsed_ms=elapsed_ms,
        )

        raise HTTPException(
            status_code=502,
            detail=ERROR_FETCH_FAILED,
        ) from exc

    elapsed_ms = round((perf_counter() - start) * 1000, 2)
    INGESTION_URL_PREVIEW_TOTAL.labels(result="success").inc()

    logger.info(
        "url_parse_preview_completed",
        url=url_str,
        status_code=response.status_code,
        content_length=len(response.content),
        parsed_char_length=parsed.char_length,
        elapsed_ms=elapsed_ms,
    )

    return UrlParsedIngestionPreview(
        url=url_str,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=len(response.content),
        elapsed_ms=elapsed_ms,
        parsed_content_type=parsed.content_type,
        parsed_char_length=parsed.char_length,
        parsed_preview=parsed.text[: runtime_settings.max_preview_text_chars],
    )


async def preview_urls(
    urls: list[AnyHttpUrl],
    max_concurrency: int,
    client: httpx.AsyncClient,
    app_settings: Settings | None = None,
) -> list[UrlIngestionBatchResult]:
    runtime_settings = _resolve_settings(app_settings)

    logger.info(
        "batch_preview_started",
        url_count=len(urls),
        max_concurrency=max_concurrency,
    )

    start = perf_counter()
    batch_limiter = create_batch_limiter(max_concurrency)

    async def preview_with_limit(url: AnyHttpUrl) -> UrlIngestionBatchResult:
        wait_start = perf_counter()
        await batch_limiter.acquire()
        INGESTION_BATCH_LIMITER_WAIT_SECONDS.observe(perf_counter() - wait_start)
        INGESTION_BATCH_IN_FLIGHT.inc()

        try:
            try:
                preview = await preview_url(
                    url,
                    client,
                    url_timeout=runtime_settings.url_timeout_seconds,
                    app_settings=runtime_settings,
                )

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
        finally:
            INGESTION_BATCH_IN_FLIGHT.dec()
            batch_limiter.release()

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


async def preview_parsed_urls(
    urls: list[AnyHttpUrl],
    max_concurrency: int,
    client: httpx.AsyncClient,
    app_settings: Settings | None = None,
) -> list[UrlParsedIngestionBatchResult]:
    runtime_settings = _resolve_settings(app_settings)

    logger.info(
        "batch_parse_preview_started",
        url_count=len(urls),
        max_concurrency=max_concurrency,
    )

    start = perf_counter()
    batch_limiter = create_batch_limiter(max_concurrency)

    async def preview_with_limit(
        url: AnyHttpUrl,
    ) -> UrlParsedIngestionBatchResult:
        wait_start = perf_counter()
        await batch_limiter.acquire()
        INGESTION_BATCH_LIMITER_WAIT_SECONDS.observe(perf_counter() - wait_start)
        INGESTION_BATCH_IN_FLIGHT.inc()

        try:
            try:
                preview = await preview_parsed_url(
                    url,
                    client,
                    url_timeout=runtime_settings.url_timeout_seconds,
                    app_settings=runtime_settings,
                )

                return UrlParsedIngestionBatchResult(
                    url=str(url),
                    success=True,
                    data=preview,
                    error=None,
                )

            except HTTPException as exc:
                return UrlParsedIngestionBatchResult(
                    url=str(url),
                    success=False,
                    data=None,
                    error=build_ingestion_error(exc),
                )
        finally:
            INGESTION_BATCH_IN_FLIGHT.dec()
            batch_limiter.release()

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
        "batch_parse_preview_completed",
        url_count=len(urls),
        success_count=success_count,
        failure_count=failure_count,
        elapsed_ms=elapsed_ms,
    )

    return results
