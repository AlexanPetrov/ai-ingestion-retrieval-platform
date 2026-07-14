"""Integration tests for health check routes."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.api.routes import health as health_routes
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app


@pytest.mark.asyncio
async def test_liveness_route_returns_ok() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_route_returns_ready_when_resources_are_available() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    app.state.http_client = None

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_http_client_is_missing() -> None:
    app = create_app(Settings(rate_limit_enabled=False))
    app.state.http_client = None

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "HTTP client unavailable"}


@pytest.mark.asyncio
async def test_original_health_route_remains_available() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_http_client_is_closed() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    shared_client = httpx.AsyncClient()
    await shared_client.aclose()
    app.state.http_client = shared_client

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "HTTP client unavailable"}


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_required_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=True,
            rate_limit_fail_open=False,
        )
    )

    async def fake_storage_ready(_request: object) -> bool:
        return False

    monkeypatch.setattr(
        health_routes,
        "is_rate_limit_storage_ready",
        fake_storage_ready,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    app.state.http_client = None

    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limit storage unavailable"}
