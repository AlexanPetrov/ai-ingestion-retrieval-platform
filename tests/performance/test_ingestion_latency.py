"""Performance-shape tests for ingestion orchestration latency.

These are intentionally small local baselines. They use mocked fetch/parser work
instead of real network, Redis, or database dependencies.
"""

import asyncio
import time

import httpx
import pytest

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionPreview,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParsedDocument
from ai_ingestion_retrieval_platform.services import ingestion as ingestion_service


def _make_preview(url: str, elapsed_ms: float) -> UrlIngestionPreview:
    return UrlIngestionPreview(
        url=url,
        status_code=200,
        content_type="text/html",
        content_length=2,
        elapsed_ms=elapsed_ms,
        preview="ok",
    )


def _make_parsed_preview(url: str, elapsed_ms: float) -> UrlParsedIngestionPreview:
    return UrlParsedIngestionPreview(
        url=url,
        status_code=200,
        content_type="text/html",
        content_length=2,
        elapsed_ms=elapsed_ms,
        parsed_content_type="text/html",
        parsed_char_length=2,
        parsed_preview="ok",
    )


@pytest.mark.asyncio
async def test_single_preview_orchestration_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_settings = Settings(max_preview_text_chars=10)
    request_count = 50
    latency_budget_seconds = 0.5

    async def fake_fetch_url(
        _client: object,
        url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/plain"},
            content=b"hello world",
            request=request,
        )

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)

    start = time.perf_counter()

    results = [
        await ingestion_service.preview_url(
            url=f"https://example.com/item-{index}",
            client=object(),
            app_settings=runtime_settings,
        )
        for index in range(request_count)
    ]

    elapsed_seconds = time.perf_counter() - start

    assert len(results) == request_count
    assert all(result.status_code == 200 for result in results)
    assert all(result.preview == "hello worl" for result in results)
    assert elapsed_seconds < latency_budget_seconds


@pytest.mark.asyncio
async def test_single_parsed_preview_orchestration_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_settings = Settings(max_preview_text_chars=10)
    request_count = 50
    latency_budget_seconds = 0.5

    async def fake_fetch_url(
        _client: object,
        url: str,
        method: str = "GET",
        url_timeout: float | None = None,
        max_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        app_settings: Settings | None = None,
    ) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/html"},
            content=b"<p>hello world</p>",
            request=request,
        )

    async def fake_parse_document(
        request: object,
        settings: object,
    ) -> ParsedDocument:
        return ParsedDocument(
            text="hello world",
            content_type="text/html",
            source_url=request.source_url,
            byte_length=len(request.content),
            char_length=11,
        )

    monkeypatch.setattr(ingestion_service, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(ingestion_service, "parse_document", fake_parse_document)

    start = time.perf_counter()

    results = [
        await ingestion_service.preview_parsed_url(
            url=f"https://example.com/item-{index}",
            client=object(),
            app_settings=runtime_settings,
        )
        for index in range(request_count)
    ]

    elapsed_seconds = time.perf_counter() - start

    assert len(results) == request_count
    assert all(result.status_code == 200 for result in results)
    assert all(result.parsed_preview == "hello worl" for result in results)
    assert elapsed_seconds < latency_budget_seconds


@pytest.mark.asyncio
async def test_batch_preview_orchestration_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url_count = 50
    max_concurrency = 10
    per_url_sleep_seconds = 0.01
    latency_budget_seconds = 0.3

    urls = [f"https://example-{index}.test" for index in range(url_count)]

    async def fake_preview_url(
        url: str,
        _client: object,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
    ) -> UrlIngestionPreview:
        await asyncio.sleep(per_url_sleep_seconds)
        return _make_preview(url, per_url_sleep_seconds * 1000)

    monkeypatch.setattr(ingestion_service, "preview_url", fake_preview_url)

    start = time.perf_counter()
    results = await ingestion_service.preview_urls(
        urls=urls,
        max_concurrency=max_concurrency,
        client=object(),
    )
    elapsed_seconds = time.perf_counter() - start

    assert [result.url for result in results] == urls
    assert all(result.success for result in results)
    assert elapsed_seconds < latency_budget_seconds


@pytest.mark.asyncio
async def test_batch_parsed_preview_orchestration_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url_count = 30
    max_concurrency = 6
    per_url_sleep_seconds = 0.01
    latency_budget_seconds = 0.3

    urls = [f"https://example-{index}.test" for index in range(url_count)]

    async def fake_preview_parsed_url(
        url: str,
        _client: object,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
    ) -> UrlParsedIngestionPreview:
        await asyncio.sleep(per_url_sleep_seconds)
        return _make_parsed_preview(url, per_url_sleep_seconds * 1000)

    monkeypatch.setattr(
        ingestion_service,
        "preview_parsed_url",
        fake_preview_parsed_url,
    )

    start = time.perf_counter()
    results = await ingestion_service.preview_parsed_urls(
        urls=urls,
        max_concurrency=max_concurrency,
        client=object(),
    )
    elapsed_seconds = time.perf_counter() - start

    assert [result.url for result in results] == urls
    assert all(result.success for result in results)
    assert elapsed_seconds < latency_budget_seconds


@pytest.mark.asyncio
async def test_batch_latency_is_dominated_by_slow_outlier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fast_sleep_seconds = 0.005
    slow_sleep_seconds = 0.05
    latency_slack_seconds = 0.15

    urls = [
        "https://fast-1.test",
        "https://fast-2.test",
        "https://fast-3.test",
        "https://slow.test",
    ]

    async def fake_preview_url(
        url: str,
        _client: object,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
    ) -> UrlIngestionPreview:
        if "slow" in url:
            await asyncio.sleep(slow_sleep_seconds)
            return _make_preview(url, slow_sleep_seconds * 1000)

        await asyncio.sleep(fast_sleep_seconds)
        return _make_preview(url, fast_sleep_seconds * 1000)

    monkeypatch.setattr(ingestion_service, "preview_url", fake_preview_url)

    start = time.perf_counter()
    results = await ingestion_service.preview_urls(
        urls=urls,
        max_concurrency=4,
        client=object(),
    )
    elapsed_seconds = time.perf_counter() - start

    assert [result.url for result in results] == urls
    assert all(result.success for result in results)
    assert elapsed_seconds >= slow_sleep_seconds
    assert elapsed_seconds < slow_sleep_seconds + latency_slack_seconds
    assert slow_sleep_seconds >= fast_sleep_seconds * 10
