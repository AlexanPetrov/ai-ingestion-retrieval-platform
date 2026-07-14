"""Integration tests for app startup/shutdown lifecycle and shared resources."""

import httpx
import pytest
from limits.aio.strategies import MovingWindowRateLimiter

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_shared_http_client() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    assert getattr(app.state, "http_client", None) is None

    async with app.router.lifespan_context(app):
        client = app.state.http_client

        assert isinstance(client, httpx.AsyncClient)
        assert client.is_closed is False

    assert client.is_closed is True
    assert app.state.http_client is None


@pytest.mark.asyncio
async def test_lifespan_initializes_and_clears_shared_rate_limiter() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=True,
            rate_limit_redis_url="async+memory://",
        )
    )

    assert getattr(app.state, "rate_limiter", None) is None

    async with app.router.lifespan_context(app):
        assert isinstance(
            app.state.rate_limiter,
            MovingWindowRateLimiter,
        )
        assert app.state.rate_limiter_storage is not None
        assert app.state.rate_limiter_storage_url == "async+memory://"

    assert app.state.rate_limiter is None
    assert app.state.rate_limiter_storage is None
    assert app.state.rate_limiter_storage_url is None


@pytest.mark.asyncio
async def test_app_health_routes_work_with_lifespan_enabled() -> None:
    app = create_app(Settings(rate_limit_enabled=False))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            live_response = await client.get("/health/live")
            ready_response = await client.get("/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok"}

    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
