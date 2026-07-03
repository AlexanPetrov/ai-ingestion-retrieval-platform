"""Performance-shape tests for batch latency and slow outlier behavior."""

import asyncio
import time

import pytest

from ai_ingestion_retrieval_platform.schemas.ingestion import UrlIngestionPreview
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


@pytest.mark.asyncio
async def test_batch_latency_is_dominated_by_slow_outlier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fast_sleep_seconds = 0.05
    slow_sleep_seconds = 0.5

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
    assert elapsed_seconds < slow_sleep_seconds + 0.2
    assert slow_sleep_seconds >= fast_sleep_seconds * 10
