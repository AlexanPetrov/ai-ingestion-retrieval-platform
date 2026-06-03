"""Integration tests for Prometheus metrics endpoint contract."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.main import app


@pytest.mark.asyncio
async def test_metrics_route_returns_prometheus_payload() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")


@pytest.mark.asyncio
async def test_metrics_route_exposes_project_metric_families() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
        response = await client.get("/metrics")

    payload = response.text

    assert "http_requests_total" in payload
    assert "http_request_duration_seconds" in payload
    assert "ingestion_url_preview_total" in payload
    assert "ingestion_batch_preview_total" in payload
    assert "ingestion_batch_duration_seconds" in payload
