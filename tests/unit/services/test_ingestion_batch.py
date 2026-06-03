"""Unit tests for batch concurrency, ordering, and partial-failure semantics."""

import asyncio

import pytest
from fastapi import HTTPException

from ai_ingestion_retrieval_platform.schemas.ingestion import UrlIngestionPreview
from ai_ingestion_retrieval_platform.services import ingestion as ingestion_service


def _make_preview(url: str) -> UrlIngestionPreview:
    return UrlIngestionPreview(
        url=url,
        status_code=200,
        content_type="text/html",
        content_length=12,
        elapsed_ms=1.23,
        preview="ok",
    )


@pytest.mark.asyncio
async def test_preview_urls_preserves_input_order_and_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_preview_url(url: str) -> UrlIngestionPreview:
        if "bad" in url:
            raise HTTPException(
                status_code=400,
                detail=ingestion_service.ERROR_TOO_MANY_REDIRECTS,
            )
        return _make_preview(url)

    monkeypatch.setattr(ingestion_service, "preview_url", fake_preview_url)

    urls = [
        "https://ok-1.test",
        "https://bad.test",
        "https://ok-2.test",
    ]

    results = await ingestion_service.preview_urls(urls=urls, max_concurrency=2)

    assert [result.url for result in results] == urls
    assert [result.success for result in results] == [True, False, True]

    failed = results[1]
    assert failed.error is not None
    assert failed.error.code == "too_many_redirects"
    assert failed.error.status_code == 400


@pytest.mark.asyncio
async def test_preview_urls_respects_max_concurrency_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_flight = 0
    peak_in_flight = 0
    lock = asyncio.Lock()

    async def fake_preview_url(url: str) -> UrlIngestionPreview:
        nonlocal in_flight, peak_in_flight
        async with lock:
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)

        await asyncio.sleep(0.01)

        async with lock:
            in_flight -= 1

        return _make_preview(url)

    monkeypatch.setattr(ingestion_service, "preview_url", fake_preview_url)

    urls = [f"https://example-{index}.test" for index in range(6)]
    results = await ingestion_service.preview_urls(urls=urls, max_concurrency=2)

    assert len(results) == 6
    assert all(result.success for result in results)
    assert peak_in_flight == 2
