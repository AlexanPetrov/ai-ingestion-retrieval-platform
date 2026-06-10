"""Unit tests for fetch behavior: redirects, caps, retries, and timeout paths."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from tenacity import stop_after_attempt, wait_none

from ai_ingestion_retrieval_platform.services import ingestion as ingestion_service


async def _allow_all_urls(_url: str) -> None:
    return


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
        str(exc_info.value.detail)
        == ingestion_service.ERROR_REDIRECT_MISSING_LOCATION
    )


@pytest.mark.asyncio
async def test_fetch_url_too_many_redirects_returns_controlled_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.settings, "max_redirects", 1)

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
            await ingestion_service.fetch_url(client, "https://example.com/start")

    assert call_count == 2
    assert exc_info.value.status_code == 400
    assert str(exc_info.value.detail) == ingestion_service.ERROR_TOO_MANY_REDIRECTS


@pytest.mark.asyncio
async def test_fetch_url_caps_response_body_by_max_preview_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.settings, "max_preview_bytes", 5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=b"abcdefghij", request=request)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await ingestion_service.fetch_url(client, "https://example.com")

    assert response.status_code == 200
    assert response.content == b"abcde"


@pytest.mark.asyncio
async def test_fetch_url_retries_retryable_http_status_and_eventually_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion_service, "validate_url_is_safe", _allow_all_urls)
    monkeypatch.setattr(ingestion_service.fetch_url.retry, "wait", wait_none())
    monkeypatch.setattr(
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(3),
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
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(5),
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
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(3),
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
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(5),
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
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(5),
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
        ingestion_service.fetch_url.retry,
        "stop",
        stop_after_attempt(2),
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
    )

    result = ingestion_service.get_retry_wait_seconds(retry_state)

    assert result == ingestion_service.settings.retry_backoff_max_seconds


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
    )

    monkeypatch.setattr(
        ingestion_service,
        "DEFAULT_RETRY_WAIT",
        lambda _state: 1.23,
    )

    result = ingestion_service.get_retry_wait_seconds(retry_state)

    assert result == 1.23


def test_fetch_url_retry_stop_policy_includes_total_timeout() -> None:
    stop_strategy = ingestion_service.fetch_url.retry.stop

    strategy_values = []
    for attr_name in ("stops", "stop_funcs"):
        strategy_values = getattr(stop_strategy, attr_name, [])
        if strategy_values:
            break

    assert strategy_values
    assert len(strategy_values) == 2

    max_attempt_stop = next(
        stop
        for stop in strategy_values
        if hasattr(stop, "max_attempt_number")
    )
    max_delay_stop = next(
        stop
        for stop in strategy_values
        if hasattr(stop, "max_delay")
    )

    assert (
        max_attempt_stop.max_attempt_number
        == ingestion_service.settings.retry_attempts
    )
    assert (
        max_delay_stop.max_delay
        == ingestion_service.settings.retry_total_timeout_seconds
    )
