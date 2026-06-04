"""Integration tests for app startup/shutdown lifecycle and shared resources."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.main import app, lifespan


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_shared_http_client() -> None:
    assert getattr(app.state, "http_client", None) is None

    async with lifespan(app):
        client = app.state.http_client
        assert isinstance(client, httpx.AsyncClient)
        assert client.is_closed is False

    assert client.is_closed is True
    assert app.state.http_client is None


@pytest.mark.asyncio
async def test_app_health_route_works_with_lifespan_enabled() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
