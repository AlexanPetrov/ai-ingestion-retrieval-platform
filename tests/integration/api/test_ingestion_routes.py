"""Integration tests for ingestion API request/response contracts."""

import httpx
import pytest

from ai_ingestion_retrieval_platform.api.dependencies.auth import (
    AUTHENTICATION_REQUIRED_DETAIL,
)
from ai_ingestion_retrieval_platform.api.routes import ingestion as ingestion_routes
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app


@pytest.mark.asyncio
async def test_url_preview_route_returns_expected_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(rate_limit_enabled=False, ingestion_auth_enabled=False)
    app = create_app(settings)

    async def fake_preview_url(
        url: object,
        _client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> dict[str, object]:
        assert app_settings is settings

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
async def test_url_parse_preview_route_returns_expected_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(rate_limit_enabled=False, ingestion_auth_enabled=False)
    app = create_app(settings)

    async def fake_preview_parsed_url(
        url: object,
        _client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> dict[str, object]:
        assert app_settings is settings

        url_str = str(url)
        return {
            "url": url_str,
            "status_code": 200,
            "content_type": "application/pdf",
            "content_length": 128,
            "elapsed_ms": 2.4,
            "parsed_content_type": "application/pdf",
            "parsed_char_length": 11,
            "parsed_preview": "hello pdf",
        }

    monkeypatch.setattr(
        ingestion_routes,
        "preview_parsed_url",
        fake_preview_parsed_url,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/parse-preview",
                json={"url": "https://example.com/file.pdf"},
            )

    app.state.http_client = None

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://example.com/file.pdf",
        "status_code": 200,
        "content_type": "application/pdf",
        "content_length": 128,
        "elapsed_ms": 2.4,
        "parsed_content_type": "application/pdf",
        "parsed_char_length": 11,
        "parsed_preview": "hello pdf",
    }
    assert response.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_urls_preview_route_forwards_urls_and_app_default_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        default_max_concurrency=4,
    )
    app = create_app(settings)
    captured: dict[str, object] = {}

    async def fake_preview_urls(
        urls: list[object],
        max_concurrency: int,
        client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> list[dict[str, object]]:
        assert isinstance(client, httpx.AsyncClient)

        normalized_urls = [str(url) for url in urls]
        captured["urls"] = normalized_urls
        captured["max_concurrency"] = max_concurrency
        captured["app_settings"] = app_settings

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
    assert captured["max_concurrency"] == settings.default_max_concurrency
    assert captured["app_settings"] is settings


@pytest.mark.asyncio
async def test_urls_parse_preview_route_forwards_urls_and_app_default_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        default_max_concurrency=4,
    )
    app = create_app(settings)
    captured: dict[str, object] = {}

    async def fake_preview_parsed_urls(
        urls: list[object],
        max_concurrency: int,
        client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> list[dict[str, object]]:
        assert isinstance(client, httpx.AsyncClient)

        normalized_urls = [str(url) for url in urls]
        captured["urls"] = normalized_urls
        captured["max_concurrency"] = max_concurrency
        captured["app_settings"] = app_settings

        return [
            {
                "url": normalized_urls[0],
                "success": True,
                "data": {
                    "url": normalized_urls[0],
                    "status_code": 200,
                    "content_type": "text/html",
                    "content_length": 10,
                    "elapsed_ms": 0.8,
                    "parsed_content_type": "text/html",
                    "parsed_char_length": 5,
                    "parsed_preview": "hello",
                },
                "error": None,
            }
        ]

    monkeypatch.setattr(
        ingestion_routes,
        "preview_parsed_urls",
        fake_preview_parsed_urls,
    )

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
            response = await client.post(
                "/ingestion/urls/parse-preview",
                json=payload,
            )

    app.state.http_client = None

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert captured["urls"] == ["https://example.com/"]
    assert captured["max_concurrency"] == settings.default_max_concurrency
    assert captured["app_settings"] is settings


@pytest.mark.asyncio
async def test_url_preview_route_rejects_invalid_url() -> None:
    app = create_app(Settings(rate_limit_enabled=False, ingestion_auth_enabled=False))

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
async def test_urls_preview_route_rejects_app_specific_concurrency_limit() -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        default_max_concurrency=2,
        max_allowed_concurrency=2,
    )
    app = create_app(settings)

    payload = {
        "urls": ["https://example.com"],
        "max_concurrency": settings.max_allowed_concurrency + 1,
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
    assert response.json() == {
        "detail": (f"max_concurrency cannot exceed {settings.max_allowed_concurrency}")
    }


@pytest.mark.asyncio
async def test_urls_preview_route_rejects_app_specific_batch_limit() -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        max_batch_urls=1,
    )
    app = create_app(settings)

    payload = {
        "urls": [
            "https://example.com/one",
            "https://example.com/two",
        ],
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
    assert response.json() == {
        "detail": f"Batch cannot contain more than {settings.max_batch_urls} URLs"
    }


@pytest.mark.asyncio
async def test_url_preview_route_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=True,
        ingestion_auth_enabled=False,
        rate_limit_redis_url="async+memory://",
        rate_limit_url_preview_requests=1,
        rate_limit_url_preview_window_seconds=60,
    )
    app = create_app(settings)

    async def fake_preview_url(
        url: object,
        _client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> dict[str, object]:
        assert app_settings is settings

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
            first_response = await client.post(
                "/ingestion/url/preview",
                json={"url": "https://example.com"},
            )
            second_response = await client.post(
                "/ingestion/url/preview",
                json={"url": "https://example.com"},
            )

    app.state.http_client = None

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json() == {"detail": "Rate limit exceeded"}
    assert int(second_response.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_urls_preview_route_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=True,
        ingestion_auth_enabled=False,
        rate_limit_redis_url="async+memory://",
        rate_limit_batch_preview_requests=1,
        rate_limit_batch_preview_window_seconds=60,
    )
    app = create_app(settings)

    async def fake_preview_urls(
        urls: list[object],
        max_concurrency: int,
        client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> list[dict[str, object]]:
        assert isinstance(client, httpx.AsyncClient)
        assert app_settings is settings

        normalized_urls = [str(url) for url in urls]
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
            first_response = await client.post("/ingestion/urls/preview", json=payload)
            second_response = await client.post("/ingestion/urls/preview", json=payload)

    app.state.http_client = None

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json() == {"detail": "Rate limit exceeded"}
    assert int(second_response.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_urls_parse_preview_route_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=True,
        ingestion_auth_enabled=False,
        rate_limit_redis_url="async+memory://",
        rate_limit_batch_preview_requests=1,
        rate_limit_batch_preview_window_seconds=60,
    )
    app = create_app(settings)

    async def fake_preview_parsed_urls(
        urls: list[object],
        max_concurrency: int,
        client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> list[dict[str, object]]:
        assert isinstance(client, httpx.AsyncClient)
        assert app_settings is settings

        normalized_urls = [str(url) for url in urls]
        return [
            {
                "url": normalized_urls[0],
                "success": True,
                "data": {
                    "url": normalized_urls[0],
                    "status_code": 200,
                    "content_type": "text/html",
                    "content_length": 10,
                    "elapsed_ms": 0.8,
                    "parsed_content_type": "text/html",
                    "parsed_char_length": 5,
                    "parsed_preview": "hello",
                },
                "error": None,
            }
        ]

    monkeypatch.setattr(
        ingestion_routes,
        "preview_parsed_urls",
        fake_preview_parsed_urls,
    )

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
            first_response = await client.post(
                "/ingestion/urls/parse-preview",
                json=payload,
            )
            second_response = await client.post(
                "/ingestion/urls/parse-preview",
                json=payload,
            )

    app.state.http_client = None

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json() == {"detail": "Rate limit exceeded"}
    assert int(second_response.headers["retry-after"]) >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/ingestion/url/preview",
            {"url": "https://example.com"},
        ),
        (
            "/ingestion/url/parse-preview",
            {"url": "https://example.com"},
        ),
        (
            "/ingestion/urls/preview",
            {"urls": ["https://example.com"]},
        ),
        (
            "/ingestion/urls/parse-preview",
            {"urls": ["https://example.com"]},
        ),
    ],
)
async def test_ingestion_routes_require_authentication_when_enabled(
    path: str,
    payload: dict[str, object],
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=True,
        ingestion_auth_token="expected-token",
    )
    app = create_app(settings)

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(path, json=payload)

    app.state.http_client = None

    assert response.status_code == 401
    assert response.json() == {
        "detail": AUTHENTICATION_REQUIRED_DETAIL,
    }
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_ingestion_route_rejects_invalid_bearer_token() -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=True,
        ingestion_auth_token="expected-token",
    )
    app = create_app(settings)

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
                headers={"Authorization": "Bearer wrong-token"},
            )

    app.state.http_client = None

    assert response.status_code == 401
    assert response.json() == {
        "detail": AUTHENTICATION_REQUIRED_DETAIL,
    }
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_ingestion_route_accepts_configured_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=True,
        ingestion_auth_token="expected-token",
    )
    app = create_app(settings)

    async def fake_preview_url(
        url: object,
        _client: httpx.AsyncClient,
        app_settings: Settings | None = None,
    ) -> dict[str, object]:
        assert app_settings is settings

        return {
            "url": str(url),
            "status_code": 200,
            "content_type": "text/plain",
            "content_length": 2,
            "elapsed_ms": 0.5,
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
                headers={"Authorization": "Bearer expected-token"},
            )

    app.state.http_client = None

    assert response.status_code == 200
    assert response.json()["preview"] == "ok"
