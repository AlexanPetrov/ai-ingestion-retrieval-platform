"""URL ingestion service with safety checks, retries, and bounded concurrency."""

import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
from time import perf_counter

import httpx
import structlog
from fastapi import HTTPException
from pydantic import AnyHttpUrl
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    wait_exponential_jitter,
)

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.limits import (
    create_batch_limiter,
    get_host_limiter,
    get_outbound_fetch_limiter,
)
from ai_ingestion_retrieval_platform.core.metrics import (
    INGESTION_BATCH_DURATION_SECONDS,
    INGESTION_BATCH_IN_FLIGHT,
    INGESTION_BATCH_LIMITER_WAIT_SECONDS,
    INGESTION_BATCH_PREVIEW_TOTAL,
    INGESTION_HOST_LIMITER_WAIT_SECONDS,
    INGESTION_OUTBOUND_IN_FLIGHT,
    INGESTION_OUTBOUND_LIMITER_WAIT_SECONDS,
    INGESTION_URL_PREVIEW_TOTAL,
    INGESTION_URL_RETRY_TOTAL,
    INGESTION_URL_TIMEOUT_TOTAL,
)
from ai_ingestion_retrieval_platform.core.url_safety import validate_url_is_safe
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionBatchResult,
    UrlIngestionError,
    UrlIngestionPreview,
    UrlParsedIngestionBatchResult,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParseRequest
from ai_ingestion_retrieval_platform.services.parsing import parse_document

logger = structlog.get_logger()

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}

ERROR_TOO_MANY_REDIRECTS = "Too many redirects"
ERROR_REDIRECT_MISSING_LOCATION = "Redirect response missing Location header"
ERROR_TIMEOUT = "URL fetch timed out"
ERROR_FETCH_FAILED = "URL fetch failed"


def _resolve_settings(app_settings: Settings | None) -> Settings:
    """Return explicitly provided app settings or freshly loaded defaults."""
    if app_settings is not None:
        return app_settings

    return Settings()


def _get_retry_settings(retry_state: RetryCallState) -> Settings:
    """Return the settings associated with the current retry call."""
    app_settings = getattr(retry_state, "kwargs", {}).get("app_settings")

    if isinstance(app_settings, Settings):
        return app_settings

    args = getattr(retry_state, "args", ())
    if len(args) >= 6 and isinstance(args[5], Settings):
        return args[5]

    return Settings()


def get_default_retry_wait_seconds(retry_state: RetryCallState) -> float:
    """Return jittered exponential backoff using the current call settings."""
    runtime_settings = _get_retry_settings(retry_state)
    wait_strategy = wait_exponential_jitter(
        initial=runtime_settings.retry_backoff_initial_seconds,
        max=runtime_settings.retry_backoff_max_seconds,
    )
    return wait_strategy(retry_state)


def should_stop_retry(retry_state: RetryCallState) -> bool:
    """Stop when the current call reaches its attempt or time budget."""
    runtime_settings = _get_retry_settings(retry_state)
    elapsed_seconds = retry_state.seconds_since_start or 0.0

    return (
        retry_state.attempt_number >= runtime_settings.retry_attempts
        or elapsed_seconds >= runtime_settings.retry_total_timeout_seconds
    )


def is_retry_safe_method(method: str | None) -> bool:
    if method is None:
        return False

    return method.upper() in RETRY_SAFE_METHODS


def get_exception_request_method(exc: BaseException) -> str | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.request.method

    if isinstance(exc, httpx.RequestError):
        return exc.request.method

    return None


def on_retry_before_sleep(retry_state: RetryCallState) -> None:
    runtime_settings = _get_retry_settings(retry_state)
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    error_type = type(exception).__name__ if exception else "unknown"

    url = "unknown"
    if len(retry_state.args) >= 2:
        url = str(retry_state.args[1])

    sleep_seconds = None
    if retry_state.next_action is not None:
        sleep_seconds = round(retry_state.next_action.sleep, 3)

    logger.warning(
        "url_fetch_retry_scheduled",
        url=url,
        error_type=error_type,
        attempt_number=retry_state.attempt_number,
        max_attempts=runtime_settings.retry_attempts,
        sleep_seconds=sleep_seconds,
    )

    INGESTION_URL_RETRY_TOTAL.labels(error_type=error_type).inc()


def is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ReadTimeout):
        return False

    request_method = get_exception_request_method(exc)
    if not is_retry_safe_method(request_method):
        return False

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.NetworkError)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES

    return False


def get_retry_after_seconds(retry_after_header: str) -> float | None:
    retry_after_header = retry_after_header.strip()

    if not retry_after_header:
        return None

    try:
        retry_after_seconds = float(retry_after_header)
        return max(0.0, retry_after_seconds)
    except ValueError:
        pass

    try:
        retry_after_datetime = parsedate_to_datetime(retry_after_header)
    except ValueError:
        return None

    if retry_after_datetime.tzinfo is None:
        retry_after_datetime = retry_after_datetime.replace(tzinfo=datetime.UTC)

    now_utc = datetime.now(datetime.UTC)
    return max(0.0, (retry_after_datetime - now_utc).total_seconds())


def get_retry_wait_seconds(retry_state: RetryCallState) -> float:
    runtime_settings = _get_retry_settings(retry_state)
    exception = retry_state.outcome.exception() if retry_state.outcome else None

    if isinstance(exception, httpx.HTTPStatusError):
        response = exception.response

        if response.status_code in {429, 503}:
            retry_after_header = response.headers.get("Retry-After")
            if retry_after_header:
                retry_after_seconds = get_retry_after_seconds(retry_after_header)

                if retry_after_seconds is not None:
                    return min(
                        retry_after_seconds,
                        runtime_settings.retry_backoff_max_seconds,
                    )

    return get_default_retry_wait_seconds(retry_state)


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


@retry(
    retry=retry_if_exception(is_retryable_exception),
    stop=should_stop_retry,
    wait=get_retry_wait_seconds,
    before_sleep=on_retry_before_sleep,
    reraise=True,
)
async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    method: str = "GET",
    url_timeout: float | None = None,
    max_bytes: int | None = None,
    app_settings: Settings | None = None,
) -> httpx.Response:
    runtime_settings = _resolve_settings(app_settings)
    timeout_seconds = (
        runtime_settings.url_timeout_seconds if url_timeout is None else url_timeout
    )
    byte_limit = runtime_settings.max_preview_bytes if max_bytes is None else max_bytes
    outbound_fetch_limiter = get_outbound_fetch_limiter(runtime_settings)

    wait_start = perf_counter()
    await outbound_fetch_limiter.acquire()
    INGESTION_OUTBOUND_LIMITER_WAIT_SECONDS.observe(perf_counter() - wait_start)
    INGESTION_OUTBOUND_IN_FLIGHT.inc()

    try:
        async with asyncio.timeout(timeout_seconds):
            current_url = httpx.URL(url)

            for _ in range(runtime_settings.max_redirects + 1):
                target = await validate_url_is_safe(str(current_url), runtime_settings)
                host_limiter = await get_host_limiter(target.hostname, runtime_settings)

                pinned_url = current_url.copy_with(host=target.resolved_ip)

                request = client.build_request(
                    method,
                    pinned_url,
                    headers={"Host": target.host_header},
                    extensions={"sni_hostname": target.hostname},
                )

                host_wait_start = perf_counter()
                await host_limiter.acquire()
                INGESTION_HOST_LIMITER_WAIT_SECONDS.observe(
                    perf_counter() - host_wait_start
                )

                try:
                    response = await client.send(request, stream=True)

                    try:
                        if response.is_redirect:
                            redirect_url = response.headers.get("location")

                            if not redirect_url:
                                raise HTTPException(
                                    status_code=400,
                                    detail=ERROR_REDIRECT_MISSING_LOCATION,
                                )

                            # Resolve relative redirects against the hostname URL.
                            # This preserves Host/SNI and keeps safety checks correct.
                            current_url = current_url.join(redirect_url)
                            continue

                        response.raise_for_status()

                        body = bytearray()

                        async for chunk in response.aiter_bytes():
                            remaining = byte_limit - len(body)

                            if remaining <= 0:
                                break

                            body.extend(chunk[:remaining])

                        response._content = bytes(body)
                        return response

                    finally:
                        await response.aclose()

                finally:
                    host_limiter.release()

            raise HTTPException(
                status_code=400,
                detail=ERROR_TOO_MANY_REDIRECTS,
            )
    finally:
        INGESTION_OUTBOUND_IN_FLIGHT.dec()
        outbound_fetch_limiter.release()


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
