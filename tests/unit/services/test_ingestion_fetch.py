"""Unit tests for fetch behavior: redirects, caps, retries, and timeout paths."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from tenacity import stop_after_attempt, wait_none

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.limits import clear_limiters
from ai_ingestion_retrieval_platform.core.response_admission import (
    ERROR_CONTENT_TYPE_MISSING,
    ERROR_CONTENT_TYPE_UNSUPPORTED,
    ERROR_DECLARED_CONTENT_TOO_LARGE,
)
from ai_ingestion_retrieval_platform.core.url_safety import SafeFetchTarget
from ai_ingestion_retrieval_platform.schemas.parsing import ParsedDocument
from ai_ingestion_retrieval_platform.services import ingestion as ingestion_service


async def _allow_all_urls(
    url: str,
    _settings: Settings,
) -> SafeFetchTarget:
    parsed = httpx.URL(url)
    host_header = parsed.host
    if parsed.port is not None:
        host_header = f"{host_header}:{parsed.port}"

    return SafeFetchTarget(
        hostname=parsed.host,
        resolved_ip="93.184.216.34",
        host_header=host_header,
    )


class _TrackingAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.was_iterated = False

    async def __aiter__(self):
        self.was_iterated = True
        yield self.content

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_fetch_url_redirect_missing_location_returns_controlled_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=302, request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_service.fetch_url(client, "https://example.com")

    assert exc_info.value.status_code == 400
    assert (
        str(exc_info.value.detail) == ingestion_service.ERROR_REDIRECT_MISSING_LOCATION
    )


@pytest.mark.asyncio
async def test_fetch_url_too_many_redirects_returns_controlled_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(max_redirects=1)

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=302,
            headers={"location": "/next-hop"},
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.com",
    ) as client:
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_service.fetch_url(
                client,
                "https://example.com/start",
                app_settings=runtime_settings,
            )

    assert call_count == 2
    assert exc_info.value.status_code == 400
    assert str(exc_info.value.detail) == ingestion_service.ERROR_TOO_MANY_REDIRECTS


@pytest.mark.asyncio
async def test_fetch_url_caps_response_body_by_max_preview_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(max_preview_bytes=5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-length": "5"},
            content=b"abcdefghij",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(
            client,
            "https://example.com",
            app_settings=runtime_settings,
        )

    assert response.status_code == 200
    assert response.content == b"abcde"


@pytest.mark.asyncio
async def test_fetch_url_respects_explicit_max_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(max_preview_bytes=5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-length": "8"},
            content=b"abcdefghij",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(
            client,
            "https://example.com",
            max_bytes=8,
            app_settings=runtime_settings,
        )

    assert response.status_code == 200
    assert response.content == b"abcdefgh"


@pytest.mark.asyncio
async def test_fetch_url_rejects_oversized_declared_content_before_body_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(max_preview_bytes=5)
    stream = _TrackingAsyncByteStream(b"abcde")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-length": "6"},
            stream=stream,
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_service.fetch_url(
                client,
                "https://example.com",
                app_settings=runtime_settings,
            )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == ERROR_DECLARED_CONTENT_TOO_LARGE
    assert stream.was_iterated is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected_detail"),
    [
        ({"content-length": "2"}, ERROR_CONTENT_TYPE_MISSING),
        (
            {
                "content-length": "2",
                "content-type": "application/octet-stream",
            },
            ERROR_CONTENT_TYPE_UNSUPPORTED,
        ),
    ],
)
async def test_fetch_url_rejects_unacceptable_content_type_before_body_iteration(
    headers: dict[str, str],
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    stream = _TrackingAsyncByteStream(b"ok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers=headers,
            stream=stream,
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_service.fetch_url(
                client,
                "https://example.com",
                allowed_content_types=("text/plain", "text/html"),
            )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == expected_detail
    assert stream.was_iterated is False


@pytest.mark.asyncio
async def test_fetch_url_accepts_parameterized_supported_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "content-length": "2",
                "content-type": "Text/HTML; charset=UTF-8",
            },
            content=b"ok",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(
            client,
            "https://example.com",
            allowed_content_types=("text/html",),
        )

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.asyncio
async def test_fetch_url_retries_retryable_http_status_and_eventually_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(3)
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(status_code=503, request=request)
        return httpx.Response(status_code=200, content=b"ok", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(client, "https://example.com")

    assert call_count == 3
    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.asyncio
async def test_fetch_url_does_not_retry_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(5)
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ReadTimeout):
            await ingestion_service.fetch_url(client, "https://example.com")

    assert call_count == 1


@pytest.mark.asyncio
async def test_fetch_url_retries_connect_error_until_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(3)
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connect failed", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await ingestion_service.fetch_url(client, "https://example.com")

    assert call_count == 3


@pytest.mark.asyncio
async def test_fetch_url_does_not_retry_connect_error_for_post_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(5)
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connect failed", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await ingestion_service.fetch_url(
                client,
                "https://example.com",
                method="POST",
            )

    assert call_count == 1


@pytest.mark.asyncio
async def test_fetch_url_does_not_retry_retryable_http_status_for_post_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(5)
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=503, request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await ingestion_service.fetch_url(
                client,
                "https://example.com",
                method="POST",
            )

    assert call_count == 1


@pytest.mark.asyncio
async def test_fetch_url_emits_retry_observability_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry, "stop", stop_after_attempt(2)
    )

    warning_calls: list[dict[str, object]] = []

    class _FakeLogger:
        def warning(self, _event: str, **kwargs: object) -> None:
            warning_calls.append(kwargs)

    retry_metric_calls: list[dict[str, str]] = []

    class _FakeRetryCounter:
        def labels(self, **labels: str) -> _FakeRetryCounter:
            self._labels = labels
            return self

        def inc(self) -> None:
            retry_metric_calls.append(dict(self._labels))

    monkeypatch.setattr(ingestion_service, "logger", _FakeLogger())
    monkeypatch.setattr(
        ingestion_service,
        "INGESTION_URL_RETRY_TOTAL",
        _FakeRetryCounter(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await ingestion_service.fetch_url(client, "https://example.com")

    assert warning_calls
    assert warning_calls[0]["url"] == "https://example.com"
    assert warning_calls[0]["attempt_number"] == 1
    assert warning_calls[0]["error_type"] == "ConnectError"
    assert retry_metric_calls == [{"error_type": "ConnectError"}]


def test_get_retry_after_seconds_parses_delta_seconds() -> None:
    result = ingestion_service.get_retry_after_seconds("3")
    assert result == 3.0


def test_get_retry_after_seconds_returns_none_for_invalid_value() -> None:
    result = ingestion_service.get_retry_after_seconds("not-a-valid-header")
    assert result is None


def test_get_retry_wait_seconds_uses_retry_after_for_429() -> None:
    runtime_settings = Settings(retry_backoff_max_seconds=2.5)
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        status_code=429,
        headers={"Retry-After": "7"},
        request=request,
    )
    exception = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=response,
    )

    retry_state = SimpleNamespace(
        outcome=SimpleNamespace(exception=lambda: exception),
        attempt_number=1,
        args=(),
        kwargs={"app_settings": runtime_settings},
    )

    result = ingestion_service.get_retry_wait_seconds(retry_state)

    assert result == runtime_settings.retry_backoff_max_seconds


def test_get_retry_wait_seconds_falls_back_when_retry_after_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        status_code=429,
        headers={"Retry-After": "invalid"},
        request=request,
    )
    exception = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=response,
    )

    retry_state = SimpleNamespace(
        outcome=SimpleNamespace(exception=lambda: exception),
        attempt_number=1,
        args=(),
        kwargs={"app_settings": Settings()},
    )

    monkeypatch.setattr(
        ingestion_service,
        "get_default_retry_wait_seconds",
        lambda _state: 1.23,
    )

    result = ingestion_service.get_retry_wait_seconds(retry_state)

    assert result == 1.23


def test_should_stop_retry_uses_app_scoped_attempt_and_time_budgets() -> None:
    runtime_settings = Settings(
        retry_attempts=3,
        retry_total_timeout_seconds=2.0,
    )

    active_state = SimpleNamespace(
        args=(),
        kwargs={"app_settings": runtime_settings},
        attempt_number=2,
        seconds_since_start=1.0,
    )
    attempts_exhausted_state = SimpleNamespace(
        args=(),
        kwargs={"app_settings": runtime_settings},
        attempt_number=3,
        seconds_since_start=1.0,
    )
    time_exhausted_state = SimpleNamespace(
        args=(),
        kwargs={"app_settings": runtime_settings},
        attempt_number=1,
        seconds_since_start=2.0,
    )

    assert ingestion_service.should_stop_retry(active_state) is False
    assert ingestion_service.should_stop_retry(attempts_exhausted_state) is True
    assert ingestion_service.should_stop_retry(time_exhausted_state) is True


@pytest.mark.asyncio
async def test_fetch_url_uses_pinned_ip_and_hostname_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)

    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url_host"] = request.url.host
        seen_request["host_header"] = request.headers.get("Host")
        seen_request["sni_hostname"] = request.extensions.get("sni_hostname")
        return httpx.Response(status_code=200, content=b"ok", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(client, "https://example.com")

    assert response.status_code == 200
    assert seen_request["url_host"] == "93.184.216.34"
    assert seen_request["host_header"] == "example.com"
    assert seen_request["sni_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_fetch_url_resolves_relative_redirect_against_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_urls: list[str] = []

    async def _validate_and_capture(
        url: str,
        settings: Settings,
    ) -> SafeFetchTarget:
        resolved_urls.append(url)
        return await _allow_all_urls(url, settings)

    monkeypatch.setattr(
        ingestion_service,
        "validate_url_is_safe",
        _validate_and_capture,
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                status_code=302,
                headers={"location": "/next-hop"},
                request=request,
            )

        return httpx.Response(status_code=200, content=b"ok", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(
            client,
            "https://example.com/start",
        )

    assert response.status_code == 200
    assert resolved_urls == [
        "https://example.com/start",
        "https://example.com/next-hop",
    ]


@pytest.mark.asyncio
async def test_preview_url_returns_expected_preview_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_settings = Settings(max_preview_text_chars=4)

    async def fake_fetch_url(
        _client: object,
        _url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, "https://example.com")
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/plain"},
            content=b"abcdef",
            request=request,
        )

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    result = await ingestion_service.preview_url(
        url="https://example.com",
        client=object(),
        app_settings=runtime_settings,
    )

    assert result.url == "https://example.com"
    assert result.status_code == 200
    assert result.content_type == "text/plain"
    assert result.content_length == 6
    assert result.preview == "abcd"


@pytest.mark.asyncio
async def test_preview_parsed_url_returns_expected_preview_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_settings = Settings(
        max_preview_text_chars=6,
        max_parse_bytes=1234,
    )

    captured: dict[str, object] = {}

    async def fake_fetch_url(
        _client: object,
        url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        captured["url"] = url
        captured["method"] = method
        captured["url_timeout"] = url_timeout
        captured["max_bytes"] = max_bytes
        captured["allowed_content_types"] = allowed_content_types
        captured["app_settings"] = app_settings

        request = httpx.Request(method, url)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/pdf"},
            content=b"raw pdf bytes",
            request=request,
        )

    async def fake_parse_document(
        request: object,
        settings: object,
    ) -> ParsedDocument:
        captured["parse_content"] = request.content
        captured["parse_content_type"] = request.content_type
        captured["parse_source_url"] = request.source_url
        captured["parse_settings"] = settings

        return ParsedDocument(
            text="parsed document text",
            content_type="application/pdf",
            source_url=request.source_url,
            byte_length=len(request.content),
            char_length=20,
        )

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(ingestion_service, "parse_document", fake_parse_document)

    result = await ingestion_service.preview_parsed_url(
        url="https://example.com/file.pdf",
        client=object(),
        app_settings=runtime_settings,
    )

    assert result.url == "https://example.com/file.pdf"
    assert result.status_code == 200
    assert result.content_type == "application/pdf"
    assert result.content_length == len(b"raw pdf bytes")
    assert result.parsed_content_type == "application/pdf"
    assert result.parsed_char_length == 20
    assert result.parsed_preview == "parsed"
    assert captured["max_bytes"] == 1234
    assert (
        captured["allowed_content_types"]
        == runtime_settings.allowed_parse_content_types
    )
    assert captured["parse_content"] == b"raw pdf bytes"
    assert captured["parse_content_type"] == "application/pdf"
    assert captured["parse_source_url"] == "https://example.com/file.pdf"
    assert captured["app_settings"] is runtime_settings
    assert captured["parse_settings"] is runtime_settings


@pytest.mark.asyncio
async def test_preview_url_maps_timeout_exception_to_504(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        _client: object,
        _url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, "https://example.com")
        raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    with pytest.raises(HTTPException) as exc_info:
        await ingestion_service.preview_url(
            url="https://example.com",
            client=object(),
        )

    assert exc_info.value.status_code == 504
    assert str(exc_info.value.detail) == ingestion_service.ERROR_TIMEOUT


@pytest.mark.asyncio
async def test_preview_url_maps_http_status_error_to_502_with_upstream_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        _client: object,
        _url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, "https://example.com")
        response = httpx.Response(status_code=503, request=request)
        raise httpx.HTTPStatusError(
            "upstream returned 503",
            request=request,
            response=response,
        )

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    with pytest.raises(HTTPException) as exc_info:
        await ingestion_service.preview_url(
            url="https://example.com",
            client=object(),
        )

    assert exc_info.value.status_code == 502
    assert str(exc_info.value.detail) == "URL returned HTTP 503"


@pytest.mark.asyncio
async def test_preview_url_maps_network_error_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        _client: object,
        _url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, "https://example.com")
        raise httpx.ConnectError("network failed", request=request)

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    with pytest.raises(HTTPException) as exc_info:
        await ingestion_service.preview_url(
            url="https://example.com",
            client=object(),
        )

    assert exc_info.value.status_code == 502
    assert str(exc_info.value.detail) == ingestion_service.ERROR_FETCH_FAILED


@pytest.mark.asyncio
async def test_preview_url_maps_asyncio_timeout_to_504(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_url(
        _client: object,
        _url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        raise TimeoutError("per-URL timeout exceeded")

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    with pytest.raises(HTTPException) as exc_info:
        await ingestion_service.preview_url(
            url="https://example.com",
            client=object(),
        )

    assert exc_info.value.status_code == 504
    assert str(exc_info.value.detail) == ingestion_service.ERROR_TIMEOUT


@pytest.mark.asyncio
async def test_fetch_url_limits_same_host_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(
        host_max_concurrency=2,
        host_limiter_cache_size=1024,
    )
    clear_limiters()

    in_flight = 0
    peak_in_flight = 0
    lock = asyncio.Lock()

    class _FakeResponse:
        def __init__(self) -> None:
            self.is_redirect = False
            self.headers: dict[str, str] = {}
            self.status_code = 200
            self._content = b""

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"ok"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def build_request(
            self,
            method: str,
            url: httpx.URL,
            headers: dict[str, str],
            extensions: dict[str, str],
        ) -> httpx.Request:
            return httpx.Request(method, url, headers=headers, extensions=extensions)

        async def send(
            self,
            request: httpx.Request,
            stream: bool = True,
        ) -> _FakeResponse:
            nonlocal in_flight, peak_in_flight
            assert stream is True

            async with lock:
                in_flight += 1
                peak_in_flight = max(peak_in_flight, in_flight)

            await asyncio.sleep(0.02)

            async with lock:
                in_flight -= 1

            return _FakeResponse()

    client = _FakeClient()

    urls = [f"https://example.com/item-{i}" for i in range(6)]
    await asyncio.gather(
        *(
            ingestion_service.fetch_url(
                client,
                url,
                app_settings=runtime_settings,
            )
            for url in urls
        )
    )

    assert peak_in_flight == 2


@pytest.mark.asyncio
async def test_fetch_url_allows_parallelism_across_different_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    runtime_settings = Settings(
        host_max_concurrency=1,
        host_limiter_cache_size=1024,
    )
    clear_limiters()

    host_in_flight: dict[str, int] = {}
    host_peak: dict[str, int] = {}
    total_in_flight = 0
    total_peak = 0
    lock = asyncio.Lock()

    class _FakeResponse:
        def __init__(self) -> None:
            self.is_redirect = False
            self.headers: dict[str, str] = {}
            self.status_code = 200
            self._content = b""

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"ok"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def build_request(
            self,
            method: str,
            url: httpx.URL,
            headers: dict[str, str],
            extensions: dict[str, str],
        ) -> httpx.Request:
            return httpx.Request(method, url, headers=headers, extensions=extensions)

        async def send(
            self,
            request: httpx.Request,
            stream: bool = True,
        ) -> _FakeResponse:
            nonlocal total_in_flight, total_peak
            assert stream is True
            host = request.headers["Host"].split(":")[0]

            async with lock:
                host_in_flight[host] = host_in_flight.get(host, 0) + 1
                host_peak[host] = max(host_peak.get(host, 0), host_in_flight[host])
                total_in_flight += 1
                total_peak = max(total_peak, total_in_flight)

            await asyncio.sleep(0.02)

            async with lock:
                host_in_flight[host] -= 1
                total_in_flight -= 1

            return _FakeResponse()

    client = _FakeClient()

    urls = [
        "https://host-a.test/a1",
        "https://host-b.test/b1",
        "https://host-a.test/a2",
        "https://host-b.test/b2",
    ]
    await asyncio.gather(
        *(
            ingestion_service.fetch_url(
                client,
                url,
                app_settings=runtime_settings,
            )
            for url in urls
        )
    )

    assert host_peak.get("host-a.test") == 1
    assert host_peak.get("host-b.test") == 1
    assert total_peak == 2
