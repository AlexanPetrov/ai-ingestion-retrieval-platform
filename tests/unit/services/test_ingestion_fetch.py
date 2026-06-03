"""Unit tests for fetch behavior: redirects, caps, retries, and timeout paths."""

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
