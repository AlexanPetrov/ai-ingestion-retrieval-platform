"""Integration tests for Prometheus metrics endpoint contract."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.core.config import get_settings
from ai_ingestion_retrieval_platform.main import create_app


@pytest.mark.asyncio
async def test_metrics_route_returns_404_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    get_settings.cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_route_returns_404_without_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_TOKEN", "test-metrics-token")
    get_settings.cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_route_returns_404_with_invalid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_TOKEN", "test-metrics-token")
    get_settings.cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_route_returns_prometheus_payload_with_valid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_TOKEN", "test-metrics-token")
    get_settings.cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer test-metrics-token"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")


@pytest.mark.asyncio
async def test_metrics_route_exposes_project_metric_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_TOKEN", "test-metrics-token")
    get_settings.cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer test-metrics-token"},
        )

    payload = response.text

    assert "http_requests_total" in payload
    assert "http_request_duration_seconds" in payload
    assert "ingestion_url_preview_total" in payload
    assert "ingestion_url_timeout_total" in payload
    assert "ingestion_batch_preview_total" in payload
    assert "ingestion_batch_duration_seconds" in payload
    assert "ingestion_outbound_limiter_wait_seconds" in payload
    assert "ingestion_batch_limiter_wait_seconds" in payload
    assert "ingestion_outbound_in_flight" in payload
    assert "ingestion_batch_in_flight" in payload
    assert "ingestion_host_limiter_wait_seconds" in payload
