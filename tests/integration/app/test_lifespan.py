"""Integration tests for app startup/shutdown lifecycle and shared resources."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.core import http_client as http_client_module
from ai_ingestion_retrieval_platform.core.http_client import get_http_client
from ai_ingestion_retrieval_platform.main import app, lifespan


@pytest.mark.asyncio
async def test_get_http_client_raises_when_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_client_module, "_client", None)

    with pytest.raises(RuntimeError, match="HTTP client has not been initialized"):
        get_http_client()


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_shared_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_client_module, "_client", None)

    async with lifespan(app):
        client = get_http_client()
        assert isinstance(client, httpx.AsyncClient)
        assert client.is_closed is False

    client_after_shutdown = get_http_client()
    assert client_after_shutdown.is_closed is True


@pytest.mark.asyncio
async def test_app_health_route_works_with_lifespan_enabled() -> None:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
