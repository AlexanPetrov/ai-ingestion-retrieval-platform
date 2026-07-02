"""Integration tests for ingestion API request/response contracts."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.api.routes import ingestion as ingestion_routes
from ai_ingestion_retrieval_platform.core.config import get_settings
from ai_ingestion_retrieval_platform.main import create_app


@pytest.mark.asyncio
async def test_url_preview_route_returns_expected_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_preview_url(
        url: object,
        _client: httpx.AsyncClient,
    ) -> dict[str, object]:
        url_str = str(url)
        return {
            "url": url_str,
            "status_code": 200,
            "content_type": "text/html",
            "content_length": 3,
            "elapsed_ms": 1.2,
            "preview": "ok",
        }

    monkeypatch.setattr(ingestion_routes, "preview_url", fake_preview_url)

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/preview",
                json={"url": "https://example.com"},
            )

    app.state.http_client = None

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://example.com/",
        "status_code": 200,
        "content_type": "text/html",
        "content_length": 3,
        "elapsed_ms": 1.2,
        "preview": "ok",
    }
    assert response.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_urls_preview_route_forwards_urls_and_default_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    async def fake_preview_urls(
        urls: list[object],
        max_concurrency: int,
        client: httpx.AsyncClient,
    ) -> list[dict[str, object]]:
        assert isinstance(client, httpx.AsyncClient)
        normalized_urls = [str(url) for url in urls]
        captured["urls"] = normalized_urls
        captured["max_concurrency"] = max_concurrency
        return [
            {
                "url": normalized_urls[0],
                "success": True,
                "data": {
                    "url": normalized_urls[0],
                    "status_code": 200,
                    "content_type": "text/plain",
                    "content_length": 2,
                    "elapsed_ms": 0.5,
                    "preview": "ok",
                },
                "error": None,
            }
        ]

    monkeypatch.setattr(ingestion_routes, "preview_urls", fake_preview_urls)

    payload = {
        "urls": ["https://example.com"],
    }

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ingestion/urls/preview", json=payload)

    app.state.http_client = None

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert captured["urls"] == ["https://example.com/"]
    assert captured["max_concurrency"] == get_settings().default_max_concurrency


@pytest.mark.asyncio
async def test_url_preview_route_rejects_invalid_url() -> None:
    app = create_app()

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/preview",
                json={"url": "not-a-url"},
            )

    app.state.http_client = None

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_urls_preview_route_rejects_concurrency_above_limit() -> None:
    app = create_app()

    payload = {
        "urls": ["https://example.com"],
        "max_concurrency": get_settings().max_allowed_concurrency + 1,
    }

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ingestion/urls/preview", json=payload)

    app.state.http_client = None

    assert response.status_code == 422
